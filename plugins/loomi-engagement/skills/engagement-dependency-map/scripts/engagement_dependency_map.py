#!/usr/bin/env python3
"""Map what depends on Bloomreach Engagement definitions, and in what order they can be removed safely.

Usage:
  python3 engagement_dependency_map.py --list KIND=FILE [--list KIND=FILE ...] [--detail KIND=FILE ...]
         (--target KIND=ID_OR_NAME ... | --targets candidates.json) [--denied KIND ...] [--out map.json]

--list     a saved list response (search_scenarios, search_segmentations, search_aggregates, list_project_variables
           and so on). Gives every object's name, status and, where the tool returns it, used_by.
--detail   a saved detail response for one object, or a file holding a list of full records (search_sms_campaigns
           lists include the customer filter). Details are searched for references to every known object by ID, by
           name where an object kind is referenced by name (consent categories), and in Jinja (project variables,
           catalogs, aggregates).
--target   the definition to check, as KIND=ID or KIND=NAME. Repeat it for a list of candidates.
--targets  a JSON file: a list of {"kind": ..., "id": ...} or {"kind": ..., "name": ...}, for example the delete and
           archive candidates from engagement-asset-cleanup.
--denied   an object kind whose tool returned HTTP 403, so it's reported as "not checked (no access)".

KIND is one of: scenario, email, sms, banner, in_app_message, segmentation, event_segmentation, customer_filter,
aggregate, running_aggregate, expression, prediction, catalog, recommendation, consent, project_variable, report,
funnel, trend, dashboard.

Prints JSON: for each target, its direct and indirect dependants (a scenario that uses a segmentation that uses the
target is indirect), how each reference was found, a verdict (blocked: something live depends on it; check first:
reports, drafts or objects of unknown status depend on it; no dependants found) with a priority (high, medium,
low), and a deletion order for the targets: leaves first, objects that reference each other together, and blocked
ones left out. Cycles are handled. Rules are in references/rules.json. Never prints editor names or field values,
only JSON paths to where a reference sits. Standard library only; no network.
"""
import argparse
import json
import re
import sys
from collections import deque
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent.parent / "references" / "rules.json"
SKIP_KEYS = {"used_by", "created_by_display_name", "edited_by_display_name", "version_id", "company_id"}
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
LIVE_ORDER = {True: 0, None: 1, False: 2}
TOKEN = re.compile(r"[A-Za-z0-9_\-]+")


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def load_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{what} {path}: can't read it as JSON ({e}).")


def records(path):
    """Records from a saved tool response, with the {"result": ...} and {"data": ...} wrappers removed."""
    data = load_json(path, "input")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {re.sub(r'[A-Za-z][A-Za-z0-9+.-]*://[^\s\'"]+', '[url]', str(d.get('error') or 'no error text'))[:200]} "
                 "This check couldn't run; don't treat it as 'nothing found'.")
    while isinstance(data, dict) and isinstance(data.get("result"), (dict, list)):
        data = data["result"]
    while isinstance(data, dict) and isinstance(data.get("data"), (dict, list)):
        data = data["data"]
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        fail(f"{path}: expected a record or a list of records.")
    out = []
    for r in data:
        if isinstance(r, str):  # a plain list of names, e.g. consent categories
            r = {"name": r}
        if isinstance(r, dict):
            out.append(r)
    return out


def split_pair(text, opt):
    if "=" not in text:
        fail(f"{opt} {text!r}: expected KIND=VALUE.")
    kind, value = text.split("=", 1)
    return kind.strip().lower(), value.strip()


def record_id(r):
    for key in ("_id", "id", "reference"):
        if r.get(key) not in (None, ""):
            return str(r[key])
    return str(r.get("name") or r.get("category") or "").strip() or None


def walk(node, path=""):
    """Yield (path, parent key, string) for every scalar value and dict key, skipping used_by and editor fields."""
    if isinstance(node, dict):
        for k in sorted(node, key=str):
            if k in SKIP_KEYS:
                continue
            sub = f"{path}.{k}" if path else str(k)
            yield sub, None, str(k)
            v = node[k]
            if isinstance(v, (str, int, float)) and not isinstance(v, bool):
                yield sub, k, str(v)
            else:
                yield from walk(v, sub)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            sub = f"{path}[{i}]"
            if isinstance(v, (str, int, float)) and not isinstance(v, bool):
                yield sub, None, str(v)
            else:
                yield from walk(v, sub)


class Graph:
    def __init__(self, rules):
        self.rules = rules
        self.live_statuses = {s.lower() for s in rules["live_statuses"]}
        self.nodes = {}
        self.uses = {}        # key -> {used key: set(how)}
        self.dependants = {}  # key -> {dependant key: set(how)}
        self.paths = {}       # (user, used) -> first JSON path where the reference sits

    def node(self, kind, oid, name=None):
        key = f"{kind}:{oid}"
        n = self.nodes.get(key)
        if n is None:
            n = self.nodes[key] = {"kind": kind, "id": oid, "name": None, "status": None, "archived": False,
                                   "seen": set(), "docs": []}
        if name and not n["name"]:
            n["name"] = str(name).strip()
        return key

    def add_record(self, kind, r, source):
        oid = record_id(r)
        if not oid:
            return None
        key = self.node(kind, oid, r.get("name") or r.get("reference") or r.get("category"))
        n = self.nodes[key]
        n["seen"].add(source)
        status = r.get("status")
        if status is None and isinstance(r.get("enabled"), bool):
            status = "active" if r["enabled"] else "inactive"
        if status is not None:
            n["status"] = str(status)
        if r.get("archived") is True:
            n["archived"] = True
        for entry in r.get("used_by") or []:
            prefix, _, uid = str(entry).rpartition("_")
            if not prefix or not uid:
                continue
            ukind = self.rules["used_by_prefixes"].get(prefix, prefix)
            self.edge(self.node(ukind, uid), key, "used_by")
        return key

    def edge(self, user, used, how, path=None):
        if user == used:
            return
        self.uses.setdefault(user, {}).setdefault(used, set()).add(how)
        self.dependants.setdefault(used, {}).setdefault(user, set()).add(how)
        if path and (user, used) not in self.paths:
            self.paths[(user, used)] = path

    def live(self, key):
        """True (live), False (not live) or None (a live kind whose status wasn't loaded)."""
        n = self.nodes[key]
        if n["archived"] or n["kind"] not in self.rules["live_kinds"]:
            return False
        if n["status"] is None:
            return None
        return n["status"].lower() in self.live_statuses

    def label(self, key):
        n = self.nodes[key]
        return f"{n['kind']} {n['name']!r}" if n["name"] else f"{n['kind']} {n['id']}"

    def brief(self, key):
        n = self.nodes[key]
        return {"kind": n["kind"], "id": n["id"], "name": n["name"]}


def scan(graph, owner, doc, targets):
    """Add an edge owner -> X for every known object X that the owner's definition references."""
    rules = graph.rules
    items = list(walk(doc))
    values = {v for _, _, v in items}
    blob = "\n".join(v for _, _, v in items)
    low_blob = blob.lower()
    tokens = set(TOKEN.findall(blob))
    min_id = rules["min_id_chars"]
    name_only = set(rules["name_only_kinds"])

    def first_path(test):
        for p, k, v in items:
            if test(k, v):
                return p
        return None

    for key in sorted(graph.nodes):
        if key == owner:
            continue
        n = graph.nodes[key]
        oid, name, kind = n["id"], n["name"], n["kind"]
        if kind in rules["name_keys"]:
            keys = set(rules["name_keys"][kind])
            wanted = {x for x in (oid, name) if x}
            p = first_path(lambda k, v: k in keys and v in wanted)
            if p:
                graph.edge(owner, key, "name", p)
                continue
        if kind not in name_only and ((len(oid) >= min_id and oid in tokens) or oid in values):
            graph.edge(owner, key, "id", first_path(lambda k, v: oid in v if len(oid) >= min_id else v == oid))
            continue
        hit = None
        for pattern in rules["jinja_patterns"].get(kind, []):
            for ref in (x for x in (name, oid) if x):
                if ref.lower() not in low_blob:
                    continue
                rx = re.compile(pattern.replace("{name}", re.escape(ref)), re.I)
                if rx.search(blob):
                    hit = first_path(lambda k, v: bool(rx.search(v)))
                    break
            if hit:
                break
        if hit:
            graph.edge(owner, key, "template", hit)
            continue
        if key in targets and name and len(name) >= rules["min_name_match_chars"] and name in values:
            graph.edge(owner, key, "name (verify)", first_path(lambda k, v: v == name))


def resolve_target(graph, kind, value, unresolved):
    exact = f"{kind}:{value}"
    if exact in graph.nodes:
        return exact
    named = sorted(k for k, n in graph.nodes.items()
                   if n["kind"] == kind and (n["name"] or "").lower() == value.lower())
    if len(named) == 1:
        return named[0]
    if len(named) > 1:
        unresolved.append({"kind": kind, "value": value,
                           "reason": f"{len(named)} objects have this name; give the ID instead",
                           "ids": [graph.nodes[k]["id"] for k in named]})
        return None
    key = graph.node(kind, value, value if kind in ("consent", "project_variable") else None)
    graph.nodes[key]["seen"].add("target only")
    return key


def reach(graph, target):
    """Breadth-first over dependants: {key: (hops, parent)}. The visited set keeps cycles finite."""
    seen = {target: (0, None)}
    queue = deque([target])
    while queue:
        cur = queue.popleft()
        for dep in sorted(graph.dependants.get(cur, {})):
            if dep not in seen:
                seen[dep] = (seen[cur][0] + 1, cur)
                queue.append(dep)
    del seen[target]
    return seen


def describe(graph, key, reached, target):
    hops, parent = reached[key]
    first_hop = parent if hops > 1 else target
    n = graph.nodes[key]
    out = {"kind": n["kind"], "id": n["id"], "name": n["name"],
           "status": n["status"] or ("archived" if n["archived"] else None),
           "live": graph.live(key), "hops": hops,
           "how": sorted(graph.uses.get(key, {}).get(first_hop, set())),
           "where": graph.paths.get((key, first_hop))}
    if hops > 1:
        chain, cur = [], parent
        while cur != target and len(chain) < graph.rules["max_path_hops"]:
            chain.append(graph.label(cur))
            cur = reached[cur][1]
        out["via"] = chain
    return out


def judge(graph, t, reached):
    rules = graph.rules
    n = graph.nodes[t]
    rows = [describe(graph, k, reached, t) for k in reached]
    rows.sort(key=lambda d: (d["hops"], LIVE_ORDER[d["live"]], d["kind"], d["name"] or "", d["id"]))
    live = [d for d in rows if d["live"] is True]
    unknown = [d for d in rows if d["live"] is None]
    reporting = [d for d in rows if d["kind"] in rules["reporting_kinds"]]
    other = [d for d in rows if d["live"] is False and d["kind"] not in rules["reporting_kinds"]]
    verify = [d for d in rows if d["how"] == ["name (verify)"]]
    reasons = []
    self_live = graph.live(t)
    if self_live:
        reasons.append(f"it is itself live ({n['status']})")
    if live:
        first = graph.label(live[0]["kind"] + ":" + live[0]["id"])
        reasons.append(f"{len(live)} live dependant(s), for example {first}")
    if unknown:
        reasons.append(f"{len(unknown)} dependant(s) whose status wasn't loaded; list that kind to check them")
    if reporting:
        reasons.append(f"{len(reporting)} report, funnel, trend, metric or dashboard dependant(s) would break")
    if other:
        reasons.append(f"{len(other)} draft, inactive, archived or supporting object(s) depend on it")
    if verify:
        reasons.append(f"{len(verify)} match(es) by name only; confirm they mean this object")
    if self_live or live:
        verdict, priority = "blocked", "high"
    elif rows:
        verdict, priority = "check first", "medium"
    else:
        verdict, priority = "no dependants found", "low"
        reasons.append("nothing that was checked references it")
    uses = sorted((dict(graph.brief(u), how=sorted(h)) for u, h in graph.uses.get(t, {}).items()),
                  key=lambda d: (d["kind"], d["name"] or "", d["id"]))
    cap = rules["max_dependants_listed"]
    return {"kind": n["kind"], "id": n["id"], "name": n["name"], "status": n["status"], "archived": n["archived"],
            "live": self_live, "found_in": sorted(n["seen"]), "verdict": verdict, "priority": priority,
            "reasons": reasons,
            "counts": {"direct": sum(1 for d in rows if d["hops"] == 1),
                       "indirect": sum(1 for d in rows if d["hops"] > 1),
                       "live": len(live), "status_unknown": len(unknown), "reporting": len(reporting)},
            "dependants": rows[:cap], "dependants_not_listed": max(0, len(rows) - cap), "uses": uses}


def deletion_order(graph, targets, reached, results):
    """Leaves first. A target is held back ("review") if something outside the list depends on it, and blocked if
    it or any dependant is live. Both pass on to every target it depends on, because the dependant stays."""
    target_set = set(targets)
    own = {}
    for t in targets:
        if graph.live(t) or any(graph.live(k) for k in reached[t]):
            own[t] = "blocked"
        elif any(k not in target_set for k in reached[t]):
            own[t] = "review"
        else:
            own[t] = "ok"
    rank = {"ok": 0, "review": 1, "blocked": 2}
    final = {}
    for t in targets:
        worst = own[t]
        for k in reached[t]:
            if k in target_set and rank[own[k]] > rank[worst]:
                worst = own[k]
        final[t] = worst
    remaining = {t for t in targets if final[t] == "ok"}
    steps = []
    while remaining:
        step = sorted(t for t in remaining if not any(d in remaining for d in graph.dependants.get(t, {})))
        if not step:  # what's left references each other
            break
        steps.append(step)
        remaining -= set(step)

    def why(t):
        if own[t] == final[t]:
            return results[t]["reasons"]
        return ["a target that depends on it is " + ("blocked" if final[t] == "blocked" else "held for review")]

    return {
        "steps": [[graph.brief(k) for k in step] for step in steps],
        "together": [graph.brief(k) for k in sorted(remaining)],
        "review_first": [dict(graph.brief(t), because=why(t)) for t in sorted(targets) if final[t] == "review"],
        "blocked": [dict(graph.brief(t), because=why(t)) for t in sorted(targets) if final[t] == "blocked"],
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character; Windows consoles default to cp1252
    p = argparse.ArgumentParser(description="Map what depends on Engagement definitions, and a safe deletion order.")
    p.add_argument("--list", action="append", default=[], metavar="KIND=FILE")
    p.add_argument("--detail", action="append", default=[], metavar="KIND=FILE")
    p.add_argument("--target", action="append", default=[], metavar="KIND=ID_OR_NAME")
    p.add_argument("--targets", metavar="FILE")
    p.add_argument("--denied", action="append", default=[], metavar="KIND")
    p.add_argument("--rules", default=str(RULES_PATH), help="rules file (default: the skill's references/rules.json)")
    p.add_argument("--out", help="also write the JSON to this file")
    a = p.parse_args()

    rules = load_json(a.rules, "rules")
    if not isinstance(rules, dict) or "live_kinds" not in rules:
        fail(f"{a.rules}: not a rules file.")
    known = set(rules["kinds"])
    graph = Graph(rules)
    checked = {"lists": {}, "details": {}}

    for opt, store, bucket in (("--list", a.list, "lists"), ("--detail", a.detail, "details")):
        for pair in store:
            kind, path = split_pair(pair, opt)
            if kind not in known:
                fail(f"{opt} {pair!r}: unknown kind {kind!r}. Use one of: {', '.join(sorted(known))}.")
            recs = records(path)
            checked[bucket][kind] = checked[bucket].get(kind, 0) + len(recs)
            for r in recs:
                key = graph.add_record(kind, r, bucket[:-1])
                if key and bucket == "details":
                    graph.nodes[key]["docs"].append(r)

    wanted = [split_pair(pair, "--target") for pair in a.target]
    if a.targets:
        doc = load_json(a.targets, "targets")
        if isinstance(doc, dict):
            doc = doc.get("targets") or doc.get("candidates") or []
        if not isinstance(doc, list):
            fail(f"{a.targets}: expected a list of {{\"kind\", \"id\" or \"name\"}}.")
        for t in doc:
            if not isinstance(t, dict) or not t.get("kind") or not (t.get("id") or t.get("name")):
                fail(f"{a.targets}: every entry needs a kind and an id or name.")
            wanted.append((str(t["kind"]).strip().lower(), str(t.get("id") or t.get("name")).strip()))
    if not wanted:
        fail("give at least one --target or a --targets file.")
    unresolved, targets = [], []
    for kind, value in wanted:
        if kind not in known:
            fail(f"target {kind}={value}: unknown kind {kind!r}. Use one of: {', '.join(sorted(known))}.")
        key = resolve_target(graph, kind, value, unresolved)
        if key and key not in targets:
            targets.append(key)
    target_set = set(targets)

    for key in sorted(graph.nodes):
        for doc in graph.nodes[key]["docs"]:
            scan(graph, key, doc, target_set)

    reached = {t: reach(graph, t) for t in targets}
    results = {t: judge(graph, t, reached[t]) for t in targets}
    supplied = set(checked["lists"]) | set(checked["details"])
    denied = sorted({d.strip().lower() for d in a.denied})
    out = {
        "ok": True,
        "checked": {"lists": dict(sorted(checked["lists"].items())),
                    "details": dict(sorted(checked["details"].items())),
                    "denied": denied,
                    "not_checked": sorted(k for k in rules["kinds"] if k not in supplied and k not in denied)},
        "targets": sorted(results.values(),
                          key=lambda r: (PRIORITY_ORDER[r["priority"]], r["kind"], r["name"] or "", r["id"])),
        "deletion_order": deletion_order(graph, targets, reached, results),
        "unresolved": unresolved,
    }
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"--out {a.out}: can't write it ({e}).")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
