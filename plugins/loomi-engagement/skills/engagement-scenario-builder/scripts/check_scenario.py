#!/usr/bin/env python3
"""Check a Bloomreach Engagement scenario payload before it's written, for the scenario builder skill.

Reads JSON the assistant has built or fetched. It never calls the network. Standard library only.

Usage:
    python3 scripts/check_scenario.py PAYLOAD_JSON [--stored STORED_JSON]

PAYLOAD_JSON  the payload about to be sent to create_scenario or update_scenario.
--stored      the saved search_scenarios detail response for the scenario being changed
              (fetched with include_node_designs=true). Adds the checks that protect it.

Prints ERROR lines (fix before writing) and WARNING lines (tell the user), then a summary.
Exits with status 1 when there are errors. Webhook headers, bodies and URLs are never printed.
"""
import argparse
import json
import re
import sys

LEGACY_SCHEDULE_KEYS = {"repeat_type", "repeat_frequency", "repeat_on_days", "start_date", "end_date", "repeat_at_time"}
OFFSET_LIMITS = {"days": 90, "weeks": 13, "months": 3}
EDITABLE = {"draft", "inactive"}


def unwrap(obj):
    """Strip the {result: {data: ...}} / {data: ...} envelopes Loomi Connect uses."""
    for _ in range(3):
        if isinstance(obj, dict) and isinstance(obj.get("result"), dict):
            obj = obj["result"]
        if isinstance(obj, dict) and obj.get("data") is not None and "nodes" not in obj:
            obj = obj["data"]
    return obj


def load(path):
    with open(path, encoding="utf-8") as f:
        return unwrap(json.load(f))


def is_trigger(t):
    return t.endswith("-trigger")


def outputs(node):
    """The valid source connector indexes for a node, or None when any index >= 1 is allowed."""
    t = node.get("type", "")
    if is_trigger(t):
        return {0}
    if t == "label":
        return set()
    if t == "condition":
        return {1, 2}
    if t == "limit":
        return {1, 2}
    if t.startswith("wait-action"):
        return {1}
    if t == "ab-split":
        return {int(v.get("id")) for v in node.get("variants") or [] if str(v.get("id", "")).lstrip("-").isdigit()}
    if t == "ab-split-contextual":
        return {int(v.get("id")) + 1 for v in node.get("variants") or [] if str(v.get("id", "")).lstrip("-").isdigit()}
    return None


def label(node):
    return f'#{node.get("id")} {node.get("name") or node.get("type")}'


def check(payload, stored):
    errors, warnings = [], []
    nodes = payload.get("nodes") or []
    conns = payload.get("connections") or []
    by_id = {}
    for n in nodes:
        if not isinstance(n.get("id"), int) or n["id"] < 0:
            errors.append(f"A node has no valid integer id: {n.get('type')}")
            continue
        if n["id"] in by_id:
            errors.append(f"Two nodes share id {n['id']}.")
        by_id[n["id"]] = n

    if "customer_filter" in payload:
        errors.append("customer_filter is set on the scenario itself. The backend drops it and the flow reaches everyone: put it on a condition node.")
    if not any(is_trigger(n.get("type", "")) for n in nodes):
        errors.append("There's no trigger node, so nothing starts the flow.")
    last = payload.get("last_node_id")
    if by_id and (not isinstance(last, int) or last < max(by_id)):
        errors.append(f"last_node_id must be at least the highest node id ({max(by_id)}).")
    if stored and isinstance(last, int) and last < int(stored.get("last_node_id") or 0):
        errors.append(f"last_node_id went below the stored value ({stored.get('last_node_id')}), so a deleted step's id could be reused.")

    into, out_used = set(), {}
    for c in conns:
        try:
            s, sp = c["source"]["node_id"], c["source"]["connector_index"]
            d, dp = c["destination"]["node_id"], c["destination"]["connector_index"]
        except (KeyError, TypeError):
            errors.append("A connection isn't in the {source: {node_id, connector_index}, destination: {...}} shape.")
            continue
        if s not in by_id or d not in by_id:
            errors.append(f"A connection points at a node that isn't in the payload ({s} -> {d}).")
            continue
        if dp != 0:
            warnings.append(f"Connection into {label(by_id[d])} uses input {dp}; it's normally 0.")
        if is_trigger(by_id[d].get("type", "")) or by_id[d].get("type") == "label":
            errors.append(f"An arrow leads into {label(by_id[d])}, which can't take one.")
        valid = outputs(by_id[s])
        if (valid is not None and sp not in valid) or (valid is None and sp < 1):
            errors.append(f"{label(by_id[s])} has no output {sp}." + (f" Valid: {sorted(valid)}." if valid else ""))
        if (s, sp) in out_used:
            errors.append(f"Output {sp} of {label(by_id[s])} leads to two steps.")
        out_used[(s, sp)] = d
        into.add(d)

    sources = {s for s, _ in out_used}
    for n in nodes:
        t = n.get("type", "")
        if t == "label":
            continue
        if is_trigger(t) and n["id"] not in sources:
            warnings.append(f"{label(n)} doesn't lead anywhere.")
        if not is_trigger(t) and n["id"] not in into:
            warnings.append(f"Nothing leads into {label(n)}, so no one will reach it.")
        if t == "condition":
            if not n.get("name"):
                errors.append(f"Condition #{n['id']} needs a name.")
            f = n.get("customer_filter") or {}
            if not f.get("filters"):
                warnings.append(f"{label(n)} has no rules, so everyone goes down 'matches'.")
            formula = str(f.get("formula", ""))
            for ref in re.findall(r"F(\d+)", formula):
                if int(ref) >= len(f.get("filters") or []):
                    errors.append(f"{label(n)}'s formula uses F{ref}, but there are only {len(f.get('filters') or [])} rules.")
        if t == "on-event-trigger" and not (n.get("event") or {}).get("type"):
            errors.append(f"{label(n)} has no event.")
        if t == "on-api-trigger" and not (n.get("trigger") or {}).get("api_trigger_id"):
            errors.append(f"{label(n)} has no API trigger chosen.")
        if t == "repeated-trigger":
            if LEGACY_SCHEDULE_KEYS & set(n):
                errors.append(f"{label(n)} uses old schedule field names ({', '.join(sorted(LEGACY_SCHEDULE_KEYS & set(n)))}).")
            if not n.get("timezone"):
                errors.append(f"{label(n)} needs a timezone.")
            repeat = n.get("repeat", "daily")
            if repeat == "hourly" and not n.get("minutes"):
                errors.append(f"{label(n)} is hourly but has no minutes.")
            if repeat != "hourly" and not n.get("times"):
                errors.append(f"{label(n)} needs times.")
            if repeat in ("weekly", "monthly") and not n.get("days"):
                warnings.append(f"{label(n)} is {repeat} with no days picked, so it may never run.")
        if t == "on-date-attribute-trigger":
            off = n.get("offset") or {}
            limit = OFFSET_LIMITS.get(off.get("units", "days"))
            if off and (limit is None or abs(int(off.get("quantity") or 0)) > limit):
                errors.append(f"{label(n)}'s offset is outside the allowed range (days ±90, weeks ±13, months ±3).")
            if not n.get("times") or not n.get("timezone"):
                errors.append(f"{label(n)} needs times and a timezone.")
        if t == "ab-split":
            total = round(sum(float(v.get("percentage") or 0) for v in n.get("variants") or []))
            if total != 100:
                errors.append(f"{label(n)}'s variants add up to {total}%, not 100%.")
        if t == "limit" and any(not str(s.get("limit", "")).strip() for s in n.get("steps") or []):
            errors.append(f"{label(n)} has no limit set.")
        if t == "per-customer-webhook-action":
            url = str(n.get("url") or "").strip()
            if not (url.startswith(("https://", "http://")) or url.startswith("{{")):
                errors.append(f"{label(n)} needs an address starting with https://.")
            if any(isinstance(h, dict) and h.get("hidden") for h in n.get("headers") or []):
                errors.append(f"{label(n)} has a header marked hidden: take its value from the stored node before writing.")

    if stored:
        status = stored.get("status")
        if status not in EDITABLE:
            errors.append(f"The stored scenario is '{status}'. Only draft or inactive scenarios can be updated: create a new draft copy instead.")
        stored_nodes = {n.get("id"): n for n in stored.get("nodes") or []}
        for n in nodes:
            old = stored_nodes.get(n.get("id"))
            if old and old.get("type") == n.get("type") and old.get("design") and not n.get("design"):
                errors.append(f"{label(n)} lost its design: fetch with include_node_designs=true and keep it, or its content is wiped.")
        dropped = [label(o) for i, o in stored_nodes.items() if i not in by_id]
        if dropped:
            warnings.append("These steps are removed: " + ", ".join(dropped) + ".")
    return errors, warnings


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("payload")
    ap.add_argument("--stored")
    a = ap.parse_args()
    payload = load(a.payload)
    stored = load(a.stored) if a.stored else None
    errors, warnings = check(payload, stored)
    for e in errors:
        print(f"ERROR: {e}")
    for w in warnings:
        print(f"WARNING: {w}")
    n = len(payload.get("nodes") or [])
    print(f"Checked {n} steps and {len(payload.get('connections') or [])} connections: {len(errors)} errors, {len(warnings)} warnings.")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
