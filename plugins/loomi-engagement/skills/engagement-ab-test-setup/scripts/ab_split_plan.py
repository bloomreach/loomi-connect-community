#!/usr/bin/env python3
"""Plan an A/B split (ab-split node) in one Bloomreach Engagement scenario, re-check it before the write, and check
the read-back afterwards.

Usage:
  python3 ab_split_plan.py plan --scenario detail.json --spec spec.json --project-id ID
         --project-name-file project.txt [--variant-node node.json] [--out plan.json]
  python3 ab_split_plan.py recheck --plan plan.json --scenario fresh.json [--out result.json]
  python3 ab_split_plan.py verify --plan plan.json --readback 1=readback.json [--out result.json]

plan: --scenario is the saved search_scenarios detail (scenario_id, include_node_designs=true). --spec is the test
spec (references/test-spec.md): the test type (message, holdout or timing), the connection to split, the split and
variant names and shares, and for a timing test the variant's wait. --variant-node is an optional saved
search_scenario_nodes detail (include_design=true) whose message becomes variant B in a message test; without it,
variant B is a copy of the control message. The plan has one change in the shape in docs/skill-authoring.md
(Engagement variant): update_scenario for a draft or inactive scenario, or, with copy_name in the spec, a new draft
copy with create_scenario for a running one.

recheck: --scenario is the scenario fetched again just before the write. Reports whether it changed since the plan.

verify: --readback 1=FILE is the search_scenarios detail fetched after the write (the new ID for a copy). Reports
the change as in_place or not_in_place. An error about the project, organisation or access stops it.

It never calls Loomi Connect: the assistant makes the one write, after confirmation. Standard library only.
"""
import argparse
import copy
import json
import re
import sys
from pathlib import Path

RULES = None
RULES_PATH = Path(__file__).resolve().parent.parent / "references" / "rules.json"
NOT_FOUND = re.compile(r"not.?found|does not exist|doesn't exist|no such", re.I)
CONTEXT_ERROR = re.compile(r"\bproject\b|organi[sz]ation|\baccount\b|workspace|permission|\baccess\b|denied|"
                           r"forbidden|unauthori[sz]ed|\b40[13]\b|\b429\b|rate.?limit|too many", re.I)
URL = re.compile(r"https?://\S+")
TESTS = ("message", "holdout", "timing")
COLUMN, ROW = 200, 150  # canvas spacing for the new nodes; layout only


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


def clean(text, n=200):
    return URL.sub("<url>", str(text))[:n]


def read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError) as e:
        fail(f"{path}: can't read it ({e}).")


def raw_json(path):
    try:
        return json.loads(read_text(path))
    except ValueError as e:
        fail(f"{path}: can't read it as JSON ({e}).")


def unwrap(path, what):
    """The record inside {result: {success, data}}; a context error stops, a not-found returns (None, text)."""
    data = raw_json(path)
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            err = str(d.get("error") or "no error text")
            if CONTEXT_ERROR.search(err):
                fail(f"{path}: Loomi Connect returned an error about the project, organisation or access "
                     f"({clean(err, 160)}). Check the project and read it again; don't treat it as 'not found'.")
            if NOT_FOUND.search(err):
                return None, clean(err)
            fail(f"{path}: the read failed ({clean(err)}), so nothing was checked. Read it again.")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    for key in ("data", "node"):
        if isinstance(data, dict) and isinstance(data.get(key), dict):
            data = data[key]
            break
    if not isinstance(data, dict):
        fail(f"{path}: expected one {what}.")
    return data, None


def scenario_record(path):
    rec, err = unwrap(path, "search_scenarios scenario_id detail")
    if rec is None:
        fail(f"{path}: the scenario wasn't found ({err}). Check the scenario ID.")
    if not isinstance(rec.get("nodes"), list) or not isinstance(rec.get("connections"), list):
        fail(f"{path}: no nodes or connections. Save the search_scenarios detail fetched with scenario_id.")
    return rec


def edge(src, out, dst, dst_in=0):
    return {"source": {"node_id": src, "connector_index": out}, "destination": {"node_id": dst, "connector_index": dst_in}}


def edge_key(c):
    s, d = c.get("source") or {}, c.get("destination") or {}
    return (s.get("node_id"), s.get("connector_index"), d.get("node_id"), d.get("connector_index"))


def edge_text(k):
    return f"{k[0]}:{k[1]} -> {k[2]}"


def as_int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and re.fullmatch(r"\d+", v.strip()):
        return int(v.strip())
    return None


def as_share(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


# ---------- plan ----------

def check_spec(spec, problems):
    test = spec.get("test")
    if test not in TESTS:
        problems.append(f"test must be one of {', '.join(TESTS)}.")
    e = spec.get("edge") if isinstance(spec.get("edge"), dict) else {}
    src, out, dst = as_int(e.get("from_node")), as_int(e.get("from_output")), as_int(e.get("to_node"))
    if src is None or out is None or dst is None:
        problems.append("edge needs from_node, from_output and to_node as whole numbers.")
    names = []
    shares = []
    for role in ("control", "variant"):
        v = spec.get(role) if isinstance(spec.get(role), dict) else {}
        name = str(v.get("name") or "").strip()
        share = as_share(v.get("percentage"))
        if not name:
            problems.append(f"{role} needs a name.")
        if share is None:
            problems.append(f"{role} needs a percentage.")
        names.append(name)
        shares.append(share)
    if all(s is not None for s in shares):
        if abs(sum(shares) - 100) > 1e-6:
            problems.append(f"control and variant percentages must add up to 100 (they add up to {sum(shares):g}).")
        if min(shares) < RULES["min_variant_percentage"]:
            problems.append("each branch needs at least min_variant_percentage in references/rules.json.")
    if names[0] and names[0].lower() == names[1].lower():
        problems.append("control and variant need different names: the readout tells them apart by name.")
    if not str(spec.get("split_name") or "").strip():
        problems.append("split_name is required (it names the split node).")
    return test, src, out, dst, names, shares


def strip_scenario(rec, drop_versions):
    payload = {k: copy.deepcopy(v) for k, v in rec.items() if k not in RULES["managed_fields"]}
    if drop_versions:
        for n in payload.get("nodes", []):
            n.pop("version", None)
    return payload


def summary(rec):
    return {"status": rec.get("status"), "edited": rec.get("edited"), "nodes": len(rec.get("nodes") or []),
            "connections": len(rec.get("connections") or []), "last_node_id": rec.get("last_node_id")}


def cmd_plan(a):
    rec = scenario_record(a.scenario)
    spec = raw_json(a.spec)
    if not isinstance(spec, dict):
        fail(f"{a.spec}: expected a JSON object (references/test-spec.md).")
    project_name = read_text(a.project_name_file).strip()
    if not project_name:
        fail(f"{a.project_name_file}: empty. Write the project's name to it.")
    problems, warnings = [], []
    test, src, out, dst, names, shares = check_spec(spec, problems)
    scenario_id = str(rec.get("_id") or rec.get("id") or "")
    if spec.get("scenario_id") and str(spec["scenario_id"]) != scenario_id:
        problems.append("the spec's scenario_id isn't the scenario in --scenario.")

    status = str(rec.get("status") or "").lower()
    copy_name = str(spec.get("copy_name") or "").strip()
    if status in RULES["writable_statuses"]:
        kind, tool = "update", "update_scenario"
        if copy_name:
            warnings.append(f"The scenario is {status}, so the split goes into it in place; copy_name is ignored.")
    elif status in RULES["copy_statuses"] and copy_name:
        kind, tool = "create", "create_scenario"
        warnings.append(f"The scenario is {status}: it's left as it is, and the split goes into a new draft copy. "
                        "Someone has to stop the running flow and switch the copy on in Engagement, or customers "
                        "could get both.")
    else:
        kind, tool = "update", "update_scenario"
        problems.append(f"The scenario's status is {status or 'missing'}. This skill writes only to "
                        f"{' or '.join(RULES['writable_statuses'])} scenarios; for a running one, add copy_name to "
                        "the spec to plan a new draft copy.")

    nodes = rec["nodes"]
    by_id = {n.get("id"): n for n in nodes if isinstance(n, dict)}
    missing_design = sorted(i for i, n in by_id.items()
                            if n.get("type") in RULES["message_node_types"] and not n.get("design"))
    if missing_design:
        problems.append("Message steps " + ", ".join(map(str, missing_design)) + " have no design in --scenario: "
                        "fetch it again with include_node_designs=true, or the write would wipe their content.")

    conns = rec["connections"]
    keys = [edge_key(c) for c in conns]
    target = None if None in (src, out, dst) else (src, out, dst, 0)
    if target is not None and target not in keys:
        problems.append(f"There's no connection {edge_text(target)} in the scenario. Pick the edge from the "
                        "scenario's connections (search_scenario_nodes lists them).")
    dnode = by_id.get(dst) if dst is not None else None
    if dst is not None and dnode is None:
        problems.append(f"Node {dst} isn't in the scenario.")
    splits = sorted(i for i, n in by_id.items() if n.get("type") in RULES["split_node_types"])
    if splits:
        warnings.append("The scenario already has a split (node " + ", ".join(map(str, splits)) + "). Two tests in "
                        "one flow muddy each other's results unless they're on separate paths.")

    timing = spec.get("timing") if isinstance(spec.get("timing"), dict) else {}
    variant_node = None
    if dnode is not None and test == "message":
        if dnode.get("type") not in RULES["message_node_types"]:
            problems.append(f"A message test splits just before a message step; node {dst} is a "
                            f"{dnode.get('type')}.")
        if a.variant_node:
            vn, err = unwrap(a.variant_node, "search_scenario_nodes node detail")
            if vn is None:
                problems.append(f"--variant-node: not found ({err}).")
            elif vn.get("type") not in RULES["message_node_types"] or not vn.get("design"):
                problems.append("--variant-node must be a message step fetched with include_design=true.")
            elif vn.get("type") != dnode.get("type"):
                problems.append(f"--variant-node is a {vn.get('type')}, the control is a {dnode.get('type')}: "
                                "test one channel at a time.")
            else:
                variant_node = vn
                warnings.append("Variant B's message comes from another step: check its consent category, sender "
                                "and personalisation suit this flow.")
        if variant_node is None and not a.variant_node:
            warnings.append("Variant B is an exact copy of the control message. Change its content in Engagement "
                            "before the flow is switched on, or the test compares two identical messages.")
    if dnode is not None and test == "timing":
        if dnode.get("type") not in RULES["timing_node_types"]:
            problems.append(f"A timing test splits just before a wait step ({', '.join(RULES['timing_node_types'])}); "
                            f"node {dst} is a {dnode.get('type')}.")
        units, count = timing.get("units"), as_int(timing.get("count"))
        if units not in RULES["wait_units"] or count is None or count < 1:
            problems.append(f"timing needs units ({', '.join(RULES['wait_units'])}) and a whole count of 1 or more.")
        elif dnode.get("units") == units and as_int(dnode.get("count")) == count:
            problems.append("The variant's wait is the same as the control's: nothing would differ.")
    if test == "holdout":
        holdout = shares[1]
        if holdout is not None and holdout > RULES["max_holdout_percentage"]:
            warnings.append(f"The holdout gets {holdout:g}% of customers: they get nothing from this point on. "
                            "Check that's intended (max_holdout_percentage in references/rules.json).")

    base = max([as_int(rec.get("last_node_id")) or 0] + [i for i in by_id if isinstance(i, int)])
    split_id, b_id = base + 1, base + 2
    payload = strip_scenario(rec, drop_versions=(kind == "create"))
    if kind == "create":
        payload["name"] = copy_name
    new_nodes = []
    added, removed = [], []
    if not problems:
        dx, dy = (as_int(dnode.get("x")) or 0), (as_int(dnode.get("y")) or 0)
        split = {"id": split_id, "type": "ab-split", "name": str(spec["split_name"]).strip(), "x": dx, "y": dy + ROW,
                 "variants": [{"id": 1, "name": names[0], "percentage": shares[0]},
                              {"id": 2, "name": names[1], "percentage": shares[1]}],
                 "highest_variant_id_used": 2, "variants_immutable": False, "touched": False}
        new_nodes.append(split)
        out_edges = [c for c in conns if (c.get("source") or {}).get("node_id") == dst]
        new_conns = [c for c in payload["connections"] if edge_key(c) != target]
        removed.append(list(target))
        add = [edge(src, out, split_id), edge(split_id, 1, dst)]
        if test in ("message", "timing"):
            if variant_node is not None:
                bnode = {k: copy.deepcopy(v) for k, v in variant_node.items()
                         if k not in ("id", "version", "x", "y", "incoming_connections", "outgoing_connections")}
            else:
                bnode = {k: copy.deepcopy(v) for k, v in dnode.items() if k != "version"}
            bnode.update({"id": b_id, "x": dx + COLUMN, "y": dy + ROW})
            if test == "timing":
                bnode["units"], bnode["count"] = timing["units"], as_int(timing["count"])
            base_name = str(bnode.get("name") or dnode.get("name") or dnode.get("type"))
            bnode["name"] = f"{base_name} ({names[1]})"
            new_nodes.append(bnode)
            add.append(edge(split_id, 2, b_id))
            for c in sorted(out_edges, key=edge_key):
                k = edge_key(c)
                add.append(edge(b_id, k[1], k[2], k[3]))
        new_conns.extend(add)
        added = [list(edge_key(c)) for c in add]
        payload["nodes"] = payload["nodes"] + new_nodes
        payload["connections"] = new_conns
        payload["last_node_id"] = max(new["id"] for new in new_nodes)
        ids = [n.get("id") for n in payload["nodes"]]
        if len(ids) != len(set(ids)):
            problems.append("Node IDs would repeat; read the scenario again.")

    after = {"split_node_id": split_id, "split_name": str(spec.get("split_name") or "").strip(),
             "test": test, "variants": [{"id": 1, "name": names[0], "percentage": shares[0]},
                                        {"id": 2, "name": names[1], "percentage": shares[1]}],
             "control_node_id": dst, "variant_node_id": b_id if test in ("message", "timing") else None,
             "variant_node_type": (dnode or {}).get("type") if test in ("message", "timing") else None,
             "edges_removed": removed, "edges_added": added,
             "edges_text": {"removed": [edge_text(e) for e in removed], "added": [edge_text(e) for e in added]},
             "timing": {"units": timing.get("units"), "count": as_int(timing.get("count"))} if test == "timing" else None,
             "metric": spec.get("metric"), "planned_end": spec.get("planned_end"), "last_node_id": payload.get("last_node_id")}
    status_out = "blocked" if problems else "ready"
    if kind == "update":
        call = {"project_id": a.project_id, "scenario_id": scenario_id, "payload": payload}
        undo = [{"tool": "update_scenario",
                 "payload": {"project_id": a.project_id, "scenario_id": scenario_id,
                             "payload": strip_scenario(rec, drop_versions=False)}}]
        undo_note = ("Puts the scenario back as it was, with update_scenario, while it's still draft or inactive. "
                     "Once a split has run, delete its branch in the Engagement UI instead.")
        target_text = f"scenario {scenario_id}"
    else:
        call = {"project_id": a.project_id, "payload": payload}
        undo = []
        undo_note = "This skill never deletes. To remove the draft copy, delete it in the Engagement UI."
        target_text = f"new draft copy of scenario {scenario_id}"
    impact = ("None: the scenario isn't running. Nothing reaches customers until someone switches it on in Engagement."
              if kind == "update" else "None: created as a draft. The running flow is unchanged.")
    ch = {"n": 1, "status": status_out, "kind": kind, "target": target_text, "tool": tool,
          "payload": call, "before": summary(rec), "after": after, "undo": undo, "undo_note": undo_note,
          "live_impact": "none", "impact_note": impact, "problems": problems, "warnings": warnings}
    return {"ok": True, "project_id": a.project_id, "project_name": project_name, "scenario_id": scenario_id,
            "changes": [ch], "batches": [[1]] if status_out == "ready" else [],
            "counts": {"ready": int(status_out == "ready"), "blocked": int(status_out == "blocked"), "no_change": 0}}


# ---------- recheck and verify ----------

def load_plan(path):
    plan = raw_json(path)
    if not isinstance(plan, dict) or not isinstance(plan.get("changes"), list) or not plan["changes"]:
        fail(f"{path}: not a plan file. Use the file ab_split_plan.py plan wrote.")
    return plan


def cmd_recheck(a):
    plan = load_plan(a.plan)
    ch = plan["changes"][0]
    rec = scenario_record(a.scenario)
    before = ch.get("before") or {}
    now = summary(rec)
    changed = [k for k in ("status", "edited", "nodes", "connections", "last_node_id") if now.get(k) != before.get(k)]
    return {"ok": True, "unchanged": not changed, "changed": changed, "planned": before, "now": now,
            "next": "Write the planned payload." if not changed else
            "The scenario changed since the plan: someone edited it. Don't write; fetch it again and plan again."}


def numbered_file(text):
    """N=FILE, split on the first "=": a plan change number and its read-back file."""
    n, sep, path = text.partition("=")
    if not sep or not path:
        raise argparse.ArgumentTypeError("use N=FILE, e.g. 1=readback.json")
    try:
        return int(n), path
    except ValueError:
        raise argparse.ArgumentTypeError(f"{n!r} isn't a change number")


def close(a, b):
    try:
        return abs(float(a) - float(b)) < 0.01
    except (TypeError, ValueError):
        return False


def cmd_verify(a):
    plan = load_plan(a.plan)
    by_n = {c.get("n"): c for c in plan["changes"] if isinstance(c, dict)}
    results = []
    for n, path in sorted(dict(a.readback).items()):
        ch = by_n.get(n)
        if ch is None or ch.get("status") != "ready":
            fail(f"--readback {n}: the plan has no ready change {n}.")
        want = ch["after"]
        res = {"n": n, "kind": ch.get("kind"), "target": ch.get("target")}
        rec, err = unwrap(path, "search_scenarios scenario_id detail")
        if rec is None:
            res.update(result="not_in_place", note=f"The scenario wasn't found ({err}). Before writing again, "
                       "search_scenarios for it: a write that errored may still have been saved.")
            results.append(res)
            continue
        res["scenario_id"] = str(rec.get("_id") or rec.get("id") or "")
        by_id = {x.get("id"): x for x in rec.get("nodes") or [] if isinstance(x, dict)}
        keys = {edge_key(c) for c in rec.get("connections") or []}
        diffs = []
        split = by_id.get(want["split_node_id"])
        if not split or split.get("type") != "ab-split":
            diffs.append(f"no ab-split node {want['split_node_id']}")
        else:
            got = sorted((v.get("id"), str(v.get("name")), v.get("percentage")) for v in split.get("variants") or [])
            exp = sorted((v["id"], v["name"], v["percentage"]) for v in want["variants"])
            if len(got) != len(exp) or any(g[0] != e[0] or g[1] != e[1] or not close(g[2], e[2])
                                           for g, e in zip(got, exp)):
                diffs.append("the split's variants differ from the plan")
        for e in want["edges_added"]:
            if tuple(e) not in keys:
                diffs.append(f"missing connection {edge_text(e)}")
        for e in want["edges_removed"]:
            if tuple(e) in keys:
                diffs.append(f"connection {edge_text(e)} is still there")
        b = want.get("variant_node_id")
        if b is not None:
            bn = by_id.get(b)
            if not bn or bn.get("type") != want.get("variant_node_type"):
                diffs.append(f"no {want.get('variant_node_type')} node {b}")
            elif want.get("timing") and (bn.get("units") != want["timing"]["units"]
                                         or as_int(bn.get("count")) != want["timing"]["count"]):
                diffs.append(f"node {b}'s wait isn't {want['timing']['count']} {want['timing']['units']}")
        elif want.get("test") == "holdout" and any(e[0] == want["split_node_id"] and e[1] == 2 for e in keys):
            diffs.append("the holdout branch leads somewhere")
        status = str(rec.get("status") or "").lower()
        allowed = ["draft"] if ch.get("kind") == "create" else RULES["writable_statuses"]
        if status not in allowed:
            res["alert"] = (f"The scenario's status is {status or 'missing'!r}. Tell the user at once; this skill "
                            "never switches flows on.")
        res["result"] = "not_in_place" if diffs else "in_place"
        if diffs:
            res["differences"] = diffs
        results.append(res)
    unchecked = sorted(n for n, c in by_n.items() if c.get("status") == "ready" and n not in dict(a.readback))
    return {"ok": True, "results": results, "not_checked": unchecked,
            "next": "Run scenario-qa on the scenario before anyone switches it on, then engagement-experiment-readout "
                    "once the test has run."}


def main():
    global RULES
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character; Windows consoles default to cp1252
    try:
        RULES = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        fail(f"{RULES_PATH}: can't read the rules ({e}).")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="build the plan for one A/B split")
    p.add_argument("--scenario", required=True, help="saved search_scenarios detail (include_node_designs=true)")
    p.add_argument("--spec", required=True, help="the test spec (references/test-spec.md)")
    p.add_argument("--project-id", required=True, help="the Engagement project ID the user confirmed")
    p.add_argument("--project-name-file", required=True, help="a text file holding the project's name")
    p.add_argument("--variant-node", help="saved search_scenario_nodes detail (include_design=true) for variant B")
    p.add_argument("--out", required=True, help="the plan file to write (it holds the payload and the undo)")
    r = sub.add_parser("recheck", help="check the scenario hasn't changed since the plan")
    r.add_argument("--plan", required=True, help="the plan file from the plan step")
    r.add_argument("--scenario", required=True, help="the scenario fetched again just before the write")
    r.add_argument("--out", help="also write the result to this file")
    v = sub.add_parser("verify", help="check the read-back after the write")
    v.add_argument("--plan", required=True, help="the plan file from the plan step")
    v.add_argument("--readback", action="append", type=numbered_file, required=True,
                   help="N=FILE: the search_scenarios detail fetched after change N")
    v.add_argument("--out", help="also write the result to this file")
    a = ap.parse_args()
    out = {"plan": cmd_plan, "recheck": cmd_recheck, "verify": cmd_verify}[a.cmd](a)
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"{a.out}: can't write it ({e}).")
    if a.cmd == "plan":
        printable = copy.deepcopy(out)
        for c in printable["changes"]:  # payloads hold whole message designs: keep them in the --out file only
            c["payload"] = "(in the --out file)"
            c["undo"] = [{"tool": u.get("tool")} for u in c.get("undo") or []]
        text = json.dumps(printable, indent=2, ensure_ascii=False)
    print(text)


if __name__ == "__main__":
    main()
