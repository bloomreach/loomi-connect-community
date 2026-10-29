#!/usr/bin/env python3
"""Summarise a saved Bloomreach Engagement scenario for the scenario explainer skill.

Reads JSON the assistant has already fetched with Loomi Connect. It never calls
the network. Standard library only.

Usage:
    python3 scripts/scenario_graph.py SCENARIO_JSON [--segmentations SEG_LIST_JSON]
                                                    [--consent CONSENT_JSON]

SCENARIO_JSON  a saved `search_scenarios` response fetched with a scenario_id.
               A saved `search_scenario_nodes` graph map also works, but it
               contains no configuration, so references aren't checked.
--segmentations  a saved `search_segmentations` list response, to check references.
--consent        a saved `get_consent_settings` response, to check consent categories.

Prints: triggers, a flow outline from each trigger (A/B branches labelled by
variant id, limit branches as within / over), references found, and structural
warnings (dangling waits, branches from removed variants, splits not adding up
to 100%). Webhook payloads, headers and URLs are never printed.
"""
import argparse
import json
import re
import sys

ACTION_PREFIXES = ("send-", "push-notification", "serve-banner")
ACTION_SUFFIXES = ("-webhook-action", "add-event-action", "set-property-action")
METRIC_RE = re.compile(r"(metrics|report_value_by_key)\(\s*['\"]([0-9a-f]{24})['\"]")


class ToolError(Exception):
    pass


def unwrap(obj, path=""):
    """Strip the {result: {data: ...}} / {data: ...} envelopes Loomi Connect uses."""
    for _ in range(3):
        for o in (obj, obj.get("result") if isinstance(obj, dict) else None):
            if isinstance(o, dict) and o.get("success") is False:
                raise ToolError(f"{path}: Loomi Connect returned an error: {o.get('error') or 'no error text'}. "
                                "This check couldn't run; don't treat it as 'nothing found'.")
        if isinstance(obj, dict) and "result" in obj and isinstance(obj["result"], dict):
            obj = obj["result"]
        if isinstance(obj, dict) and "data" in obj and obj.get("data") is not None:
            obj = obj["data"]
    return obj


def load(path):
    with open(path, encoding="utf-8") as f:
        return unwrap(json.load(f), path)


def is_trigger(t):
    return t.endswith("-trigger")


def is_action(t):
    return t.startswith(ACTION_PREFIXES) or t.endswith(ACTION_SUFFIXES)


def describe_trigger(n):
    t = n.get("type", "")
    if t == "repeated-trigger" and "repeat" in n:
        times = ", ".join(f"{x.get('hour', 0):02d}:{x.get('minute', 0):02d}" for x in n.get("times") or [])
        days = n.get("days") or []
        when = n.get("repeat", "?")
        if days:
            when += f" on weekday(s) {days}"
        if len(n.get("times") or []) > 6:
            times = f"{len(n['times'])} times a day"
        return f"repeats {when} at {times} ({n.get('timezone', 'project timezone')})"
    if t == "now-trigger":
        return "manual 'run now'" + ("" if n.get("active") else " (not active)")
    return t


def node_label(n):
    name = n.get("name")
    base = f"[{n['id']}] {n.get('type')}"
    return f"{base} \"{name}\"" if name else base


def as_int(x):
    try:
        return int(float(str(x).strip().rstrip("%")))
    except (TypeError, ValueError):
        return None


def branch_label(n, idx):
    """Name an output (connector_index) of a branching node."""
    t = n.get("type")
    if t == "condition":
        return {1: "yes", 2: "no"}.get(idx, str(idx))
    if t == "limit":
        return {1: "within limit", 2: "over limit"}.get(idx, str(idx))
    if t in ("ab-split", "ab-split-contextual"):
        offset = 1 if t == "ab-split-contextual" else 0  # contextual outputs are id + 1
        for v in n.get("variants") or []:
            if as_int(v.get("id")) is not None and as_int(v.get("id")) + offset == idx:
                return v.get("name") or f"variant {v.get('id')}"
        return f"output {idx}: no such variant" if n.get("variants") else str(idx)
    return ""


def summarise_node(n):
    t = n.get("type", "")
    bits = []
    if t == "condition" and "customer_filter" in n:
        cf = n.get("customer_filter") or {}
        kinds = [f.get("type") + (":" + f["attribute"].get("type") if f.get("attribute") else "")
                 for f in cf.get("filters") or []]
        bits.append(f"formula {cf.get('formula') or '(none)'}; atoms {kinds}")
    elif t in ("ab-split", "ab-split-contextual") and "variants" in n:
        bits.append(", ".join(f"{v.get('name')} {v.get('percentage')}%" for v in n.get("variants") or []))
    elif t == "limit" and "steps" in n:
        bits.append("limit " + ", ".join(str(s.get("limit")) for s in n.get("steps") or []))
    elif (t.startswith("send-") or t.startswith("push-")) and "consent_category" in n:
        bits.append(f"consent {n.get('consent_category') or '-'}; template {n.get('template_id') or 'inline'}")
    elif t.endswith("-webhook-action") and "url" in n:
        url = n.get("url") or ""
        host = re.sub(r"^https?://([^/]+).*$", r"\1", url) if url else "?"
        bits.append(f"{n.get('method', '?')} to host {host} (payload not shown)")
    elif t == "condition-raw":
        bits.append("custom Jinja condition")
    return f"{node_label(n)}" + (f": {'; '.join(bits)}" if bits else "")


def collect_refs(nodes):
    refs = []
    for n in nodes:
        cf = n.get("customer_filter") or {}
        for f in cf.get("filters") or []:
            a = f.get("attribute") or {}
            if a.get("id"):
                refs.append((n["id"], a.get("type"), a["id"]))
        if n.get("template_id"):
            refs.append((n["id"], "template", n["template_id"]))
        if n.get("consent_category"):
            refs.append((n["id"], "consent_category", n["consent_category"]))
        for s in n.get("steps") or []:
            if isinstance(s, dict) and s.get("id"):
                refs.append((n["id"], f"{n.get('type')}-step", s["id"]))
        text = " ".join(str(n.get(k) or "") for k in ("jinja_filter", "data"))
        for kind, mid in METRIC_RE.findall(text):
            refs.append((n["id"], "metric" if kind == "metrics" else "report", mid))
    return refs


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scenario")
    ap.add_argument("--segmentations")
    ap.add_argument("--consent")
    args = ap.parse_args()

    sc = load(args.scenario)
    nodes = [n for n in sc.get("nodes") or [] if isinstance(n, dict) and "id" in n]
    by_id = {n["id"]: n for n in nodes}
    conns = sc.get("connections") or []
    if not conns:  # graph-map format keeps edges on each node
        for n in nodes:
            conns.extend(n.get("outgoing_connections") or [])
    out_edges, in_count = {}, {}
    for c in conns:
        s, d = c["source"], c["destination"]
        out_edges.setdefault(s["node_id"], []).append((s.get("connector_index", 0), d["node_id"]))
        in_count[d["node_id"]] = in_count.get(d["node_id"], 0) + 1

    name = sc.get("name") or sc.get("scenario_name") or "?"
    print(f"# {name} (status: {sc.get('status', '?')})")
    labels = [n for n in nodes if n.get("type") == "label"]
    if labels:
        print(f"\n{len(labels)} canvas note(s). First lines:")
        for n in labels[:5]:
            first = (n.get("text") or "").strip().splitlines()[:1]
            print(f"  - {first[0][:100] if first else ''}")

    triggers = [n for n in nodes if is_trigger(n.get("type", ""))]
    print("\n## Triggers")
    for t in triggers:
        print(f"- {node_label(t)}: {describe_trigger(t)}")
    if not triggers:
        print("- none")

    print("\n## Flow outline")
    seen = set()

    def walk(nid, depth, branch):
        n = by_id.get(nid)
        if n is None:
            return
        prefix = "  " * depth + (f"({branch}) " if branch else "")
        if nid in seen:
            print(f"{prefix}-> joins {node_label(n)}")
            return
        seen.add(nid)
        print(f"{prefix}{summarise_node(n)}")
        for idx, dest in sorted(out_edges.get(nid, [])):
            walk(dest, depth + 1, branch_label(n, idx))

    for t in triggers:
        walk(t["id"], 0, "")

    warnings = []
    for n in nodes:
        t, nid = n.get("type", ""), n["id"]
        if t == "label":
            continue
        if is_trigger(t) and not out_edges.get(nid):
            warnings.append(f"Orphan trigger {node_label(n)}: no outgoing connection")
        elif not is_trigger(t) and not in_count.get(nid):
            kind = "action" if is_action(t) else "node"
            warnings.append(f"Disconnected {kind} {node_label(n)}: nothing leads to it, so it never runs")
        if t in ("ab-split", "ab-split-contextual"):
            if not out_edges.get(nid):
                warnings.append(f"{node_label(n)} has no branches (group assignment only?)")
            if n.get("variants"):
                for idx, _ in out_edges.get(nid, []):
                    if branch_label(n, idx).endswith("no such variant"):
                        warnings.append(f"{node_label(n)}: a connection leaves output {idx}, but no variant has that "
                                        "id (removed variant?), so the steps after it never run")
                shares = [as_int(v.get("percentage")) for v in n["variants"]]
                if None not in shares and sum(shares) != 100:
                    warnings.append(f"{node_label(n)}: variant percentages add up to {sum(shares)}%, not 100%")
        if t.startswith("wait-action") and not out_edges.get(nid):
            warnings.append(f"Dangling wait {node_label(n)}: nothing follows it, so customers just wait and leave")
        if t in ("condition", "limit") and not out_edges.get(nid):
            warnings.append(f"{node_label(n)} leads nowhere: none of its branches connect to a step")
    if not triggers:
        warnings.append("No trigger node")
    elif all(t.get("type") == "now-trigger" and not t.get("active") for t in triggers):
        warnings.append("Only inactive manual triggers")

    refs = collect_refs(nodes)
    seg_ids, seg_archived = None, set()
    if args.segmentations:
        segs = load(args.segmentations)
        seg_ids = {s["_id"] for s in segs}
        seg_archived = {s["_id"] for s in segs if s.get("archived")}
    consent_ids = None
    if args.consent:
        c = load(args.consent)
        consent_ids = {x.get("id") for x in (c.get("categories") or [])}

    print("\n## References")
    if not refs:
        print("- none found" + (" (graph map has no configuration)" if not any("customer_filter" in n for n in nodes) else ""))
    for nid, kind, rid in refs:
        status = "not checked"
        if kind == "segmentation" and seg_ids is not None:
            status = "ARCHIVED" if rid in seg_archived else ("ok" if rid in seg_ids else "MISSING")
        elif kind == "consent_category" and consent_ids is not None:
            status = "ok" if rid in consent_ids else "MISSING"
        print(f"- node {nid}: {kind} {rid} [{status}]")
        if status in ("MISSING", "ARCHIVED"):
            warnings.append(f"Node {nid} references {status.lower()} {kind} {rid}")

    print("\n## Warnings")
    for w in warnings or ["none"]:
        print(f"- {w}")


if __name__ == "__main__":
    try:
        main()
    except ToolError as e:
        sys.exit(str(e))
    except (OSError, ValueError, KeyError) as e:
        sys.exit(f"error: {e}")
