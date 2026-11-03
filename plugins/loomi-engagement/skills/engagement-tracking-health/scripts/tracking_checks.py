#!/usr/bin/env python3
"""Tracking-health checks on data already fetched from Loomi Connect.

Usage:
  python3 tracking_checks.py schema SCHEMA.json
  python3 tracking_checks.py volumes SCHEMA.json CURRENT.json PREVIOUS.json [BASELINE_90D.json] [--drop 40] [--min-volume 50]

SCHEMA.json  : raw output of get_event_schema.
CURRENT.json : raw output of execute_analytics_eql for
               "select count any event by any event type grouping top N in last 7 days".
PREVIOUS.json: the same query run with execution_time = now - 7 days.
BASELINE_90D : optional, the same query with "in last 90 days". The current week
               is taken out of it, so avg_week_90d is the average of the
               previous 83 days, per week.

Prints JSON. Standard library only; no network access.
"""
import argparse
import difflib
import json
import re
import sys

SAFE_NAME = re.compile(r"^[A-Za-z0-9_\-. ]{1,64}$")


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for o in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(o, dict) and o.get("success") is False:
            print(json.dumps({"ok": False, "error": f"{path}: Loomi Connect returned an error: "
                              f"{o.get('error') or 'no error text'}. This check couldn't run; "
                              "don't treat it as 'nothing found'."}))
            sys.exit(1)
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    return data


def schema_events(schema):
    events = (schema.get("data") or schema).get("events") or []
    out = []
    for e in events:
        props = []
        for group in (e.get("properties") or {}).values():
            if isinstance(group, dict):
                props.extend(group.get("properties") or [])
        out.append((e, props))
    return out


def eql_counts(result):
    data = result.get("data") or {}
    counts = {}
    for row in data.get("rows") or []:
        header = (row.get("headers") or [{}])[0]
        if header.get("type") != "single":
            continue
        values = row.get("values") or [0]
        counts[str(header.get("value"))] = values[0] or 0
    return counts


def looks_like_typo(a, b):
    """True for pairs like chat_id/chatid or colour/color; False for plurals and numbered series."""
    if a.replace("_", "") == b.replace("_", ""):
        return True
    ta, tb = a.split("_"), b.split("_")
    if len(ta) != len(tb):
        return False
    diff = [(x, y) for x, y in zip(ta, tb) if x != y]
    if len(diff) != 1:
        return False
    x, y = diff[0]
    if x.isdigit() or y.isdigit() or x + "s" == y or y + "s" == x or min(len(x), len(y)) < 4:
        return False
    return difflib.SequenceMatcher(None, x, y).ratio() >= 0.88


def check_schema(schema):
    events = schema_events(schema)
    suspicious, unused, type_conflicts, near_dupes = [], [], [], []
    prop_types = {}
    for e, props in events:
        name = e.get("type", "")
        if not SAFE_NAME.match(name):
            suspicious.append(name)
        if not e.get("used", True):
            unused.append(name)
        names = [p.get("property", "") for p in props]
        for p in props:
            prop_types.setdefault(p.get("property"), {}).setdefault(p.get("type"), []).append(name)
            if not p.get("used", True):
                unused.append(f"{name}.{p.get('property')}")
        lowered = sorted(set(n.lower() for n in names))
        for i, a in enumerate(lowered):
            for b in lowered[i + 1:]:
                if looks_like_typo(a, b):
                    near_dupes.append(f"{name}: {a} / {b}")
    for prop, types in prop_types.items():
        if len(types) > 1:
            type_conflicts.append({"property": prop, "types": {t: sorted(ev)[:5] for t, ev in types.items()}})
    # Random-looking names: long, several digits, no separators (e.g. "x7q2...k9").
    for e, _ in events:
        name = e.get("type", "")
        if (name not in suspicious and len(name) >= 10 and sum(ch.isdigit() for ch in name) >= 3
                and not re.search(r"[_\- ]", name)):
            suspicious.append(name)
    # Families of look-alike names sharing a 12-character prefix, typical of injected or scanner traffic.
    families = {}
    for e, _ in events:
        families.setdefault(e.get("type", "")[:12], []).append(e.get("type", ""))
    prefixes = {k: len(v) for k, v in families.items() if len(v) > 3}
    return {
        "event_types": len(events),
        "suspicious_event_type_names": {"count": len(suspicious), "lookalike_families": prefixes,
                                        "samples": [s[:60] for s in suspicious[:5]]},
        "unused_in_schema": unused[:50],
        "property_type_conflicts": sorted(type_conflicts, key=lambda c: c["property"])[:30],
        "near_duplicate_property_names": near_dupes[:30],
    }


def check_volumes(schema, cur, prev, base, drop_pct, min_volume):
    known = {e.get("type") for e, _ in schema_events(schema)}
    c, p = eql_counts(cur), eql_counts(prev)
    b = eql_counts(base) if base else {}
    rows = []
    for t in sorted(known | set(c) | set(p) | set(b)):
        now, before = c.get(t, 0), p.get(t, 0)
        # The 90-day count includes this week: take it out so a brand-new type can show as "new".
        weekly_base = round(max(b.get(t, 0) - now, 0) / (83 / 7), 1) if base else None
        change = round((now / before - 1) * 100, 1) if before else None
        if now == 0 and (before > 0 or (weekly_base or 0) > 0):
            status = "stopped"
        elif now == 0:
            status = "silent (no recent events)"
        elif before == 0 and not (weekly_base or 0):
            status = "new"
        elif max(now, before) < min_volume:
            status = "low volume"
        elif change is not None and change <= -drop_pct:
            status = "dropped"
        elif change is not None and change >= drop_pct * 2.5:
            status = "spiked"
        elif weekly_base and now >= weekly_base * 2.5:
            status = "spiked vs 90-day average"
        else:
            status = "ok"
        if t not in known:
            status += " (not in schema)"
        rows.append({"event_type": t[:60], "last_7d": now, "previous_7d": before,
                     "change_pct": change, "avg_week_90d": weekly_base, "status": status})
    order = {"stopped": 0, "dropped": 1, "new": 2, "spiked": 3, "silent": 4, "low": 5, "ok": 6}
    rows.sort(key=lambda r: (order.get(r["status"].split(" ")[0], 9), -r["previous_7d"]))
    return {"total_last_7d": sum(c.values()), "total_previous_7d": sum(p.values()), "event_types": rows}


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("schema")
    s.add_argument("schema")
    v = sub.add_parser("volumes")
    v.add_argument("schema")
    v.add_argument("current")
    v.add_argument("previous")
    v.add_argument("baseline", nargs="?")
    v.add_argument("--drop", type=float, default=40, help="%% fall that counts as a drop")
    v.add_argument("--min-volume", type=int, default=50, help="ignore changes below this weekly count")
    a = ap.parse_args()
    if a.cmd == "schema":
        out = check_schema(load(a.schema))
    else:
        out = check_volumes(load(a.schema), load(a.current), load(a.previous),
                            load(a.baseline) if a.baseline else None, a.drop, a.min_volume)
    json.dump(out, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
