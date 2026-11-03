#!/usr/bin/env python3
"""Map an Engagement project's scenarios onto the standard lifecycle flows, from saved Loomi Connect output.

Usage:
  python3 lifecycle_coverage.py --scenario s1.json --scenario s2.json [--list scenarios.json]
      [--audience FLOW=FILE_OR_NUMBER ...] [--aov N] [--reachable SHARE] [--out coverage.json]

Inputs:
  --scenario   a saved search_scenarios response for one scenario_id (the full definition with
               nodes and connections). Repeat it, or give a comma-separated list of files.
  --list       optional: the saved search_scenarios list (all statuses). Scenarios whose names
               suggest a lifecycle flow but weren't fetched are reported as "not checked".
  --audience   FLOW=VALUE, split on the first "=". FLOW is a key under "flows" in
               references/rules.json (welcome, browse_abandonment, cart_abandonment,
               post_purchase, replenishment, birthday, win_back, sunset). VALUE is a number or a
               saved execute_analytics_eql result (every row's values are added up, null rows
               included). The count is divided by the flow's audience_months to give a monthly
               audience (birthday counts everyone with a birth date, so it is divided by 12).
  --aov        average order value, for the revenue at stake. Without it, no money is shown.
  --reachable  share (0-1) of each audience that can be messaged. Defaults to
               default_reachable_share in references/rules.json (an assumption).

Prints JSON (or writes it to --out):
  flows:       one entry per lifecycle flow, in rules order, with
               status       live, weak (live but late, disconnected or with no message step),
                            stopped, draft or missing (no confirmed scenario);
               scenarios    the confirmed matches, each with confidence (high: the trigger
                            proves it; medium: a scheduled trigger and the names say so),
                            evidence, problems, channels and first-message wait;
               monthly_audience, value_monthly (audience x reachable x conversion x AOV),
               at_stake_monthly (full value when missing, draft or stopped; weak_share_at_stake
               of it when weak; 0 when live), priority (high, medium, low or none) and handoff.
  unconfirmed: name-only matches (low confidence) and list entries that weren't fetched.
  assumptions: every rate and share used, so the answer can state them.

Standard library only; no network access. Writes nothing to Bloomreach.
"""
import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

# The rules live in references/rules.json, so a threshold changes in one place.
RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
MISSING = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}
STATUS_RANK = ["live", "weak", "stopped", "draft"]
UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800}
CHANNELS = (("whatsapp", "whatsapp"), ("mms", "mms"), ("sms", "sms"), ("email", "email"), ("push", "push"),
            ("inbox", "app inbox"), ("rcs", "rcs"))


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def number(v):
    """A number from a tool value ("$1,000.00", "2.50%", "(12.00)"), or None when missing or not a number."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if not isinstance(v, str):
        return None
    s = v.strip()
    if s.lower() in MISSING:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    if s[:1] in ("−", "–"):
        s = "-" + s[1:]
    if s.startswith("-"):
        negative, s = not negative, s[1:]
    s = re.sub(r"[$£€,%\s]", "", s)
    m = re.match(r"[+]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", s)
    if not m:
        return None
    x = float(m.group(0))
    if not math.isfinite(x):
        return None
    return -x if negative else x


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        fail(f"{path}: can't read the file ({e.strerror or e}).")
    except json.JSONDecodeError as e:
        fail(f"{path}: not valid JSON ({e}).")
    for _ in range(3):
        if isinstance(data, dict) and isinstance(data.get("result"), dict) and len(data) == 1:
            data = data["result"]
        if isinstance(data, dict) and data.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {data.get('error') or 'no error text'}. "
                 "This check couldn't run; don't treat it as 'nothing found'.")
        if isinstance(data, dict) and "success" in data and "data" in data:
            data = data["data"]
    return data


def files(values):
    out = []
    for v in values or []:
        out += [p.strip() for p in v.split(",") if p.strip()]
    return out


def pair(text):
    """FLOW=VALUE, split on the first "="."""
    name, sep, value = text.partition("=")
    if not sep or not name.strip() or not value.strip():
        raise argparse.ArgumentTypeError(f"expected FLOW=FILE_OR_NUMBER, got {text!r}")
    return name.strip(), value.strip()


def eql_total(data):
    """Add up every value in an EQL report's rows (null, "" and other rows included); empty rows is 0."""
    if isinstance(data, dict) and isinstance(data.get("data"), dict) and "rows" in data["data"]:
        data = data["data"]
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return None
    total = 0.0
    for r in rows:
        for v in (r.get("values") if isinstance(r, dict) else None) or []:
            x = number(v)
            total += x or 0.0
    return total


def strings(obj):
    """Every string inside a JSON value, lower-cased (for filter constants and property names)."""
    if isinstance(obj, str):
        yield obj.lower()
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


def is_message(node_type, rules):
    t = node_type.lower()
    return t.startswith(tuple(rules["message_node_prefixes"])) and not any(x in t for x in rules["message_node_exclude"])


def channel_of(node_type):
    t = node_type.lower()
    for key, name in CHANNELS:
        if key in t:
            return name
    return "other"


def wait_seconds(node):
    if not str(node.get("type", "")).startswith("wait"):
        return 0.0
    count = number(node.get("count")) or 0.0
    units = str(node.get("units") or "seconds").lower().rstrip("s")
    return count * UNIT_SECONDS.get(units, 0)


def first_message_wait(start_ids, nodes, out_edges, rules):
    """Shortest total wait (hours) from any start node to a message node, or None if none is reachable."""
    best = {i: 0.0 for i in start_ids}
    todo = sorted(start_ids)
    found = None
    while todo:
        todo.sort(key=lambda i: (best[i], str(i)))
        cur = todo.pop(0)
        node = nodes.get(cur, {})
        if cur not in start_ids and is_message(str(node.get("type", "")), rules):
            found = best[cur] if found is None else min(found, best[cur])
            continue
        for nxt in out_edges.get(cur, []):
            cost = best[cur] + wait_seconds(nodes.get(nxt, {}))
            if nxt not in best or cost < best[nxt]:
                best[nxt] = cost
                if nxt not in todo:
                    todo.append(nxt)
    return None if found is None else round(found / 3600, 2)


def graph(sc):
    nodes = {n.get("id"): n for n in sc.get("nodes") or [] if isinstance(n, dict)}
    out_edges = {}
    for c in sc.get("connections") or []:
        try:
            src, dst = c["source"]["node_id"], c["destination"]["node_id"]
        except (KeyError, TypeError):
            continue
        out_edges.setdefault(src, [])
        if dst not in out_edges[src]:
            out_edges[src].append(dst)
    return nodes, out_edges


def reachable_from(start_ids, out_edges):
    seen, stack = set(start_ids), list(start_ids)
    while stack:
        for nxt in out_edges.get(stack.pop(), []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def keyword_hit(texts, keywords):
    for kw in keywords:
        for t in texts:
            if kw in t:
                return kw
    return None


def classify(sc, rules):
    """Return (matches, problems, channels, wait_hours) for one scenario definition."""
    flows = rules["flows"]
    nodes, out_edges = graph(sc)
    triggers = sorted((i for i, n in nodes.items() if str(n.get("type", "")).endswith("-trigger")), key=str)
    names = [str(sc.get("name") or "").lower()] + sorted(
        str(n.get("name")).lower() for n in nodes.values() if n.get("name") and n.get("type") != "label")
    scheduled = any(nodes[t].get("type") not in ("on-event-trigger",) and "date-attribute" not in nodes[t].get("type", "")
                    for t in triggers)
    matches = {}

    for t in triggers:
        n = nodes[t]
        ttype = n.get("type", "")
        if ttype == "on-event-trigger":
            event = n.get("event") or {}
            ev = str(event.get("type") or "").lower()
            constants = set(strings(event.get("filter")))
            for key in rules["flow_order"]:
                f = flows[key]
                if ev and ev in [e.lower() for e in f.get("trigger_events", [])] and \
                        not constants & set(x.lower() for x in f.get("exclude_filter_values", [])):
                    matches[key] = ("high", f"on-event trigger on `{event.get('type')}`")
        elif "date-attribute" in ttype:
            props = " ".join(strings(n.get("attribute")))
            for key in rules["flow_order"]:
                hit = keyword_hit([props], flows[key].get("date_properties", []))
                if hit:
                    matches[key] = ("high", f"date-attribute trigger on a `{hit}` property")

    # A purchase trigger is post-purchase unless the first message waits long enough (or the names say so).
    wait_hours = first_message_wait(set(triggers), nodes, out_edges, rules) if triggers else None
    for key in rules["flow_order"]:
        f = flows[key]
        if key in matches and "min_first_wait_days" in f:
            long_wait = wait_hours is not None and wait_hours >= f["min_first_wait_days"] * 24
            if long_wait or keyword_hit(names, f["keywords"]):
                for other in rules["flow_order"]:
                    if other != key and other in matches and "min_first_wait_days" not in flows[other] and \
                            matches[other][1] == matches[key][1]:
                        del matches[other]
            else:
                del matches[key]

    filter_text = " ".join(s for n in nodes.values() if n.get("type") == "condition" for s in strings(n.get("customer_filter")))
    for key in rules["flow_order"]:
        if key in matches:
            continue
        f = flows[key]
        hit = keyword_hit(names, f.get("keywords", []))
        prop = keyword_hit([filter_text], f.get("date_properties", [])) if filter_text else None
        if scheduled and (hit or prop):
            why = f"names mention '{hit}'" if hit else f"a condition uses a `{prop}` property"
            matches[key] = ("medium", f"scheduled trigger; {why}")
        elif hit:
            matches[key] = ("low", f"name only ('{hit}'); the trigger doesn't confirm it")
    if any(c in ("high", "medium") for c, _ in matches.values()):
        matches = {k: v for k, v in matches.items() if v[0] != "low"}

    problems = []
    if not triggers:
        problems.append("no trigger")
    for t in triggers:
        if not out_edges.get(t):
            problems.append("trigger isn't connected to the flow")
            break
    reach = reachable_from(set(triggers), out_edges)
    messages = [nodes[i] for i in reach if i in nodes and is_message(str(nodes[i].get("type", "")), rules)]
    if triggers and not messages:
        problems.append("no message step on a connected path")
    channels = sorted({channel_of(str(m.get("type", ""))) for m in messages})
    return matches, problems, channels, wait_hours


def scenario_records(paths):
    out = []
    for p in paths:
        data = load(p)
        for d in data if isinstance(data, list) else [data]:
            if not isinstance(d, dict) or not isinstance(d.get("nodes"), list):
                fail(f"{p}: no scenario definition (nodes and connections) found; save search_scenarios with a scenario_id.")
            out.append(d)
    return out


def build(scenarios, listing, audiences, aov, reachable, rules):
    flows = rules["flows"]
    found = {k: [] for k in rules["flow_order"]}
    unconfirmed = []
    fetched = set()
    for sc in scenarios:
        sid = str(sc.get("_id") or sc.get("id") or "")
        fetched.add(sid)
        matches, problems, channels, wait_hours = classify(sc, rules)
        status = rules["status_map"].get(str(sc.get("status") or "").lower(), "stopped")
        for key in rules["flow_order"]:
            if key not in matches:
                continue
            conf, evidence = matches[key]
            entry = {"id": sid, "name": sc.get("name"), "scenario_status": sc.get("status"), "confidence": conf,
                     "evidence": evidence, "channels": channels, "first_message_wait_hours": wait_hours}
            if conf == "low":
                unconfirmed.append({"flow": key, **entry, "reason": "name only"})
                continue
            p = list(problems)
            limit = flows[key].get("max_first_wait_hours")
            if limit is not None and wait_hours is not None and wait_hours > limit:
                p.append(f"first message after {wait_hours:g} hours (over {limit})")
            entry["problems"] = p
            entry["status"] = "weak" if status == "live" and p else status
            found[key].append(entry)

    for rec in listing:
        sid = str(rec.get("_id") or rec.get("id") or "")
        if sid in fetched:
            continue
        name = str(rec.get("name") or "").lower()
        for key in rules["flow_order"]:
            hit = keyword_hit([name], flows[key].get("keywords", []))
            if hit:
                unconfirmed.append({"flow": key, "id": sid, "name": rec.get("name"), "scenario_status": rec.get("status"),
                                    "reason": f"not checked: name mentions '{hit}'"})

    out_flows = []
    for key in rules["flow_order"]:
        f = flows[key]
        entries = sorted(found[key], key=lambda e: (STATUS_RANK.index(e["status"]), {"high": 0, "medium": 1}[e["confidence"]],
                                                     str(e["name"]), e["id"]))
        status = entries[0]["status"] if entries else "missing"
        monthly = None
        if key in audiences:
            monthly = round(audiences[key] / (f.get("audience_months") or 1), 1)
        value = None
        if monthly is not None and aov is not None and f.get("revenue", True):
            value = round(monthly * reachable * f["conversion_rate"] * aov, 2)
        at_stake = None
        if value is not None:
            at_stake = 0.0 if status == "live" else round(value * (rules["weak_share_at_stake"] if status == "weak" else 1), 2)
        handoff = {"missing": "engagement-scenario-builder", "live": "engagement-scenario-performance"}.get(status, "scenario-qa")
        out_flows.append({"flow": key, "label": f["label"], "status": status, "scenarios": entries,
                          "monthly_audience": monthly, "conversion_rate": f["conversion_rate"],
                          "revenue_flow": bool(f.get("revenue", True)), "value_monthly": value,
                          "at_stake_monthly": at_stake, "handoff": handoff})

    total = round(sum(x["at_stake_monthly"] or 0 for x in out_flows), 2)
    for x in out_flows:
        if x["status"] == "live":
            x["priority"] = "none"
        elif x["monthly_audience"] is not None and x["monthly_audience"] < rules["min_monthly_audience"]:
            x["priority"], x["at_stake_monthly"] = "low", None
        elif x["at_stake_monthly"] and total and x["at_stake_monthly"] / total >= rules["high_share_of_total"]:
            x["priority"] = "high"
        else:
            x["priority"] = "medium"

    unconfirmed.sort(key=lambda u: (rules["flow_order"].index(u["flow"]), str(u["name"]), u["id"]))
    return {"ok": True,
            "summary": {s: sum(1 for x in out_flows if x["status"] == s) for s in ["live", "weak", "stopped", "draft", "missing"]},
            "total_at_stake_monthly": total if aov is not None else None,
            "flows": out_flows, "unconfirmed": unconfirmed,
            "assumptions": {"aov": aov, "reachable_share": reachable,
                            "conversion_rates": {k: flows[k]["conversion_rate"] for k in rules["flow_order"]},
                            "weak_share_at_stake": rules["weak_share_at_stake"],
                            "note": "Conversion rates and the default reachable share are planning assumptions, not benchmarks."}}


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenario", action="append", help="saved search_scenarios detail (repeat, or comma-separated)")
    ap.add_argument("--list", help="saved search_scenarios list, all statuses (optional)")
    ap.add_argument("--audience", action="append", type=pair, default=[], help="FLOW=FILE_OR_NUMBER (repeat)")
    ap.add_argument("--aov", help="average order value")
    ap.add_argument("--reachable", type=float, default=RULES["default_reachable_share"],
                    help=f"reachable share 0-1 (default {RULES['default_reachable_share']}, from references/rules.json)")
    ap.add_argument("--out", help="write the JSON here (a path in your working folder) instead of printing it")
    a = ap.parse_args()

    if not 0 <= a.reachable <= 1:
        fail("--reachable must be a share between 0 and 1.")
    aov = None
    if a.aov is not None:
        aov = number(a.aov)
        if aov is None or aov < 0:
            fail(f"--aov must be a positive number, got {a.aov!r}.")
    audiences = {}
    for flow, value in a.audience:
        if flow not in RULES["flows"]:
            fail(f"unknown flow {flow!r}; use one of: {', '.join(RULES['flow_order'])}.")
        if os.path.exists(value):
            total = eql_total(load(value))
            if total is None:
                fail(f"{value}: no EQL rows found; save the execute_analytics_eql result for the {flow} audience.")
        else:
            total = number(value)
            if total is None:
                fail(f"--audience {flow}: {value!r} is neither a file nor a number.")
        audiences[flow] = total

    listing = []
    if a.list:
        data = load(a.list)
        listing = [r for r in (data if isinstance(data, list) else []) if isinstance(r, dict)]
    result = build(scenario_records(files(a.scenario)), listing, audiences, aov, a.reachable, RULES)
    text = json.dumps(result, indent=1, ensure_ascii=False)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"{a.out}: can't write the file ({e.strerror or e}).")
        print(json.dumps({"ok": True, "out": a.out, "summary": result["summary"],
                          "total_at_stake_monthly": result["total_at_stake_monthly"]}))
    else:
        print(text)


if __name__ == "__main__":
    main()
