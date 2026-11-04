#!/usr/bin/env python3
"""Plan one Bloomreach Engagement scenario clone before it runs, find it again after an error, and verify it afterwards.

Usage:
  python3 scenario_clone_plan.py plan --source source.json --preview preview.json --source-project-id ID
         --source-project-name NAME --project-id ID --project-name NAME --source-org ORG --target-org ORG
         --target-scenarios list.json [--cross-org-confirmed] [--name-suffix TEXT] [--today YYYY-MM-DD] [--on-conflict DEP_ID=duplicate|use_old ...]
         [--target-events F] [--target-properties F] [--target-consent F] [--target-frequency-policies F]
         [--target-integrations F] [--target-catalogs F] [--target-variables F]
         [--source-recommendations F ...] [--source-catalogs F] [--initiative-id ID] [--out plan.json]
  python3 scenario_clone_plan.py find --plan plan.json --scenarios list.json [--since UNIX_SECONDS] [--out F]
  python3 scenario_clone_plan.py verify --plan plan.json --readback 1=readback.json [--out result.json]

plan: --source is the search_scenarios scenario_id detail of the source scenario (include_node_designs=true),
--preview the preview_clone_scenario result, --target-scenarios a search_scenarios list of the target project
(archived=null, so archived names count too). The --target-* files are saved results from the target project:
get_event_schema, get_customer_property_schema, get_consent_settings, get_frequency_policies, search_integrations,
search_catalogs and list_project_variables. --source-recommendations are search_recommendations details from the
source project for engines the clone would create, and --source-catalogs the source's search_catalogs list, so the
plan can check each engine's catalog exists in the target. --source-org and --target-org name each project's
organisation: a copy between organisations is blocked until the user confirms it (--cross-org-confirmed), and is
always blocked when the source has webhooks. It prints a plan in the shape in docs/skill-authoring.md
("Plan files for write skills"), with project_id and project_name for the target, the clone_scenario payload with
an on_conflict for every dependency that already exists (never replace), and a fix list of every reference that
won't resolve in the target. Webhook headers, bodies and URLs are never printed.

find: lists target scenarios with the planned name (and, with --since, any created since then whose name contains
the source name). Run it before cloning again after an error.

verify: --readback 1=FILE is the search_scenarios scenario_id detail of the clone in the target. Reports in_place
or not_in_place, and an alert when its status isn't draft or inactive. An error about the project, organisation,
account or access stops it.

It never calls Loomi Connect: the assistant makes the one clone_scenario call, after confirmation. Standard library only.
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
NOT_FOUND = re.compile(r"not.?found|does not exist|doesn't exist|no such", re.I)
CONTEXT_ERROR = re.compile(r"\bproject\b|organi[sz]ation|\baccount\b|workspace|permission|\baccess\b|denied|"
                           r"forbidden|unauthori[sz]ed|\b40[13]\b|\b429\b|rate.?limit|too many", re.I)
URL = re.compile(r"\b[a-z][a-z0-9+.\-]*://\S+", re.I)
JINJA_REFS = {
    "aggregate": re.compile(r"aggregates\s*\[\s*['\"]([^'\"]+)['\"]\s*\]"),
    "expression": re.compile(r"expressions\s*\[\s*['\"]([^'\"]+)['\"]\s*\]"),
    "recommendation_engine": re.compile(r"recommendations\s*\(\s*['\"]([^'\"]+)['\"]"),
}
CATALOG_REF = re.compile(r"catalogs\s*(?:\[\s*['\"]([^'\"]+)['\"]\s*\]|\.\s*([A-Za-z_][A-Za-z0-9_]*))")
VARIABLE_REF = re.compile(r"project_variables?\s*(?:\.\s*([A-Za-z_][A-Za-z0-9_]*)|\[\s*['\"]([^'\"]+)['\"]\s*\])")
ID_TYPES = ("aggregate", "expression", "segmentation", "prediction")
MANAGED_KEYS = ("_id", "id", "status", "created", "edited", "created_by_display_name", "edited_by_display_name")


def norm(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


def redact(text, limit=200):
    """Error or warning text with URLs removed (they can carry tokens), cut to a length."""
    return URL.sub("<url removed>", str(text))[:limit]


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


def check_error(path, data, not_found_ok=False):
    """A success:false result: context errors stop; a not-found returns its text when allowed; others stop."""
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            err = str(d.get("error") or "no error text")
            if CONTEXT_ERROR.search(err):
                fail(f"{path}: Loomi Connect returned an error about the project, account or access ({redact(err, 160)}). "
                     "This step couldn't run; check the project and read it again. Don't treat it as 'nothing found'.")
            if not_found_ok and NOT_FOUND.search(err):
                return redact(err)
            fail(f"{path}: the tool returned an error ({redact(err)}). This step couldn't run.")
    return None


def unwrap(data):
    if isinstance(data, dict) and isinstance(data.get("result"), (dict, list)):
        data = data["result"]
    if isinstance(data, dict) and isinstance(data.get("data"), (dict, list)):
        data = data["data"]
    return data


def load(path):
    data = raw_json(path)
    check_error(path, data)
    return unwrap(data)


def rows(data, *keys):
    """The list of records in a saved tool result: the data itself, or the first list under one of keys."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for k in keys:
            if isinstance(data.get(k), list):
                return [r for r in data[k] if isinstance(r, dict)]
    return []


def scenario_record(path, label):
    data = raw_json(path)
    check_error(path, data)
    rec = unwrap(data)
    if not isinstance(rec, dict) or not isinstance(rec.get("nodes"), list):
        fail(f"{path}: expected one search_scenarios scenario_id detail ({label}) with a nodes list.")
    return rec


# ---------- reading a scenario ----------

def type_has(node, words):
    t = str(node.get("type") or "").lower()
    return any(w in t for w in words)


def shape(rec):
    """The parts of a scenario a clone should keep: node types, connections and trigger types."""
    nodes = [n for n in rec.get("nodes") or [] if isinstance(n, dict)]
    types = {}
    for n in nodes:
        t = str(n.get("type") or "unknown")
        types[t] = types.get(t, 0) + 1
    triggers = sorted({str(n.get("type")) for n in nodes if "trigger" in str(n.get("type") or "")})
    return {"node_count": len(nodes), "node_types": dict(sorted(types.items())),
            "connection_count": len([c for c in rec.get("connections") or [] if isinstance(c, dict)]),
            "trigger_types": triggers}


def webhooks(rec):
    """Webhook nodes, described without their headers, body or URL."""
    out = []
    for n in rec.get("nodes") or []:
        if not isinstance(n, dict) or not type_has(n, RULES["webhook_type_words"]):
            continue
        parts = n.get("parametrized_parts") if isinstance(n.get("parametrized_parts"), dict) else {}
        has_headers = bool(n.get("headers") or parts.get("headers"))
        has_body = any(v for k, v in list(n.items()) + list(parts.items()) if "body" in str(k).lower())
        out.append({"node_id": n.get("id"), "name": str(n.get("name") or "")[:80], "has_headers": has_headers,
                    "has_body": bool(has_body), "has_auth_integration": bool(n.get("auth_integration_id"))})
    return sorted(out, key=lambda w: str(w["node_id"]))


class Refs:
    """Every name or ID a scenario refers to, with the nodes that use it."""

    def __init__(self):
        self.found = {}

    def add(self, kind, ref, node):
        if ref is None or str(ref).strip() == "":
            return
        key = (kind, ref if isinstance(ref, tuple) else str(ref))
        self.found.setdefault(key, set()).add(node)

    def items(self, kind):
        return sorted((k[1], v) for k, v in self.found.items() if k[0] == kind)


def event_spec(d):
    return isinstance(d, dict) and isinstance(d.get("type"), str) and isinstance(d.get("filter"), list)


def walk(obj, refs, node, ctx):
    if isinstance(obj, dict):
        if event_spec(obj):
            refs.add("event", obj["type"], node)
            ctx = obj["type"]
        elif event_spec(obj.get("event")):
            ctx = obj["event"]["type"]
        t = obj.get("type")
        if t == "property" and isinstance(obj.get("property"), str):
            if ctx:
                refs.add("event_property", (ctx, obj["property"]), node)
            else:
                refs.add("customer_property", obj["property"], node)
        elif t == "consent" and isinstance(obj.get("category"), str):
            refs.add("consent_category", obj["category"], node)
        elif t in ID_TYPES and isinstance(obj.get("id"), str):
            refs.add("id_reference", (t, obj["id"]), node)
        for k, v in sorted(obj.items()):
            if k == "consent_category" and isinstance(v, str):
                refs.add("consent_category", v, node)
            elif k == "tracking_consent_categories" and isinstance(v, list):
                for c in v:
                    if isinstance(c, str):
                        refs.add("consent_category", c, node)
            elif k == "frequency_policy" and isinstance(v, str):
                refs.add("frequency_policy", v, node)
            elif str(k).endswith("integration_id") and isinstance(v, str):
                refs.add("integration", v, node)
            walk(v, refs, node, ctx)
    elif isinstance(obj, list):
        for v in obj:
            walk(v, refs, node, ctx)
    elif isinstance(obj, str) and ("{{" in obj or "{%" in obj):
        for t, rx in sorted(JINJA_REFS.items()):
            for m in rx.finditer(obj):
                refs.add("id_reference", (t, m.group(1)), node)
        for m in CATALOG_REF.finditer(obj):
            name = m.group(1) or m.group(2)
            if name not in RULES["ignored_catalog_words"]:
                refs.add("catalog", name, node)
        for m in VARIABLE_REF.finditer(obj):
            refs.add("project_variable", m.group(1) or m.group(2), node)


def collect_refs(rec):
    refs = Refs()
    for n in rec.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        label = str(n.get("name") or n.get("type") or n.get("id"))[:80]
        if "trigger" in str(n.get("type") or "") and event_spec(n.get("event")):
            refs.add("trigger_event", n["event"]["type"], label)
        walk({k: v for k, v in n.items() if k not in MANAGED_KEYS}, refs, label, None)
    return refs


# ---------- target look-ups ----------

def target_names(path, kind):
    """The set of names (or IDs) a saved target look-up holds, or None when the file wasn't given."""
    if not path:
        return None
    data = load(path)
    if kind == "event":
        recs = rows(data, "events")
        return {str(e.get("type")): event_props(e) for e in recs if e.get("type")}
    if kind == "customer_property":
        return {str(p.get("property") or p.get("name")) for p in rows(data, "properties")
                if p.get("property") or p.get("name")}
    if kind == "consent_category":
        return {str(c.get("id")) for c in rows(data, "categories") if c.get("id")}
    if kind == "frequency_policy":
        return {str(p.get("id")) for p in rows(data, "policies") if p.get("id")}
    if kind == "integration":
        return {str(i.get("id") or i.get("_id")) for i in rows(data, "integrations") if i.get("id") or i.get("_id")}
    if kind == "catalog":
        return {str(c.get("name")) for c in rows(data, "catalogs") if c.get("name")}
    if kind == "project_variable":
        return {str(v.get("reference") or v.get("name")) for v in rows(data, "variables")
                if v.get("reference") or v.get("name")}
    return None


def event_props(e):
    props = e.get("properties")
    names = set()
    groups = props.values() if isinstance(props, dict) else [props]
    for g in groups:
        recs = g.get("properties") if isinstance(g, dict) else g
        if isinstance(recs, list):
            for p in recs:
                if isinstance(p, dict) and (p.get("property") or p.get("name")):
                    names.add(str(p.get("property") or p.get("name")))
    return names


FIXES = {
    "trigger_event": "The event that starts the flow isn't tracked in the target. Track it there first, or change the "
                     "trigger to an event the target has (engagement-scenario-builder), before anyone switches it on.",
    "event": "This event isn't tracked in the target, so the condition or aggregate never matches. Track it, or change "
             "the step to an event the target has.",
    "event_property": "The event exists in the target but without this property. Track the property, or change the filter.",
    "customer_property": "No such customer property in the target. Import or track it, or change the condition.",
    "consent_category": "No consent category with this ID in the target. Pick the target's equivalent category on the "
                        "message step and in the consent condition.",
    "frequency_policy": "No frequency policy with this ID in the target. Pick one of the target's policies on the step.",
    "integration": "Integrations belong to one project. Pick the target's integration (or create it) on the step; a "
                   "webhook that used it has no authentication until then.",
    "catalog": "No catalog with this name in the target. Import the catalog, or change the Jinja to a target catalog.",
    "engine_catalog": "The clone creates this recommendation engine, but its catalog isn't in the target. Import the "
                      "catalog, or point the engine at a target catalog, before the engine can return items.",
    "project_variable": "No project variable with this name in the target. Add it in the target's project settings.",
    "id_reference": "The clone didn't list this ID as a dependency, so it still points at the source project's item. "
                    "Replace it with the target's equivalent in the step.",
}


def ref_entry(kind, ref, nodes, problem):
    return {"priority": RULES["ref_priority"].get(kind, "medium"), "kind": kind, "ref": ref,
            "nodes": sorted(nodes)[:5], "problem": problem, "fix": FIXES[kind]}


def check_refs(refs, a, dep_ids, mode):
    """The fix list: every reference that won't resolve in the target, and the kinds that couldn't be checked."""
    fixes, not_checked = [], set()
    if mode == "same_project":
        return fixes, []
    looked = {
        "event": target_names(a.target_events, "event"),
        "customer_property": target_names(a.target_properties, "customer_property"),
        "consent_category": target_names(a.target_consent, "consent_category"),
        "frequency_policy": target_names(a.target_frequency_policies, "frequency_policy"),
        "integration": target_names(a.target_integrations, "integration"),
        "catalog": target_names(a.target_catalogs, "catalog"),
        "project_variable": target_names(a.target_variables, "project_variable"),
    }
    events = looked["event"]
    for kind in ("trigger_event", "event"):
        for name, nodes in refs.items(kind):
            if events is None:
                not_checked.add("event")
            elif name not in events:
                if kind == "event" and refs.found.get(("trigger_event", name)):
                    continue
                fixes.append(ref_entry(kind, name, nodes, f"event '{name}' isn't in the target's event schema"))
    for (ev, prop), nodes in refs.items("event_property"):
        if events is None:
            not_checked.add("event")
        elif ev in events and prop not in events[ev]:
            fixes.append(ref_entry("event_property", f"{ev}.{prop}", nodes,
                                   f"event '{ev}' has no property '{prop}' in the target"))
    for kind in ("customer_property", "consent_category", "frequency_policy", "integration", "catalog",
                 "project_variable"):
        have = looked[kind]
        for name, nodes in refs.items(kind):
            if have is None:
                not_checked.add(kind)
            elif name not in have:
                fixes.append(ref_entry(kind, name, nodes, f"{kind.replace('_', ' ')} '{name}' isn't in the target"))
    for (t, rid), nodes in refs.items("id_reference"):
        if rid not in dep_ids:
            fixes.append(ref_entry("id_reference", f"{t} {rid}", nodes,
                                   f"{t} ID '{rid}' isn't in the clone's dependency list"))
    order = {"high": 0, "medium": 1, "low": 2}
    fixes.sort(key=lambda f: (order.get(f["priority"], 3), f["kind"], str(f["ref"])))
    return fixes, sorted(not_checked)


def engine_catalog_fixes(a, deps):
    """For each recommendation engine the clone creates, check its source catalog's name exists in the target."""
    new_engines = [d for d in deps if d["type"] == "recommendation_engine" and not d["exists"]]
    if not new_engines:
        return [], []
    if not a.source_recommendations or not a.source_catalogs or not a.target_catalogs:
        return [], ["engine_catalog"]
    engines = {}
    for path in a.source_recommendations:
        data = load(path)
        for rec in ([data] if isinstance(data, dict) else rows(data)):
            rid = str(rec.get("id") or rec.get("_id") or "")
            if rid:
                engines[rid] = rec
    source_cats = {str(c.get("_id") or c.get("id")): str(c.get("name")) for c in rows(load(a.source_catalogs), "catalogs")}
    target_cats = target_names(a.target_catalogs, "catalog")
    fixes, missing = [], []
    for d in new_engines:
        rec = engines.get(d["id"]) or {}
        cat = rec.get("catalog")
        cat_id = str(rec.get("catalog_id") or (cat.get("id") or cat.get("_id") if isinstance(cat, dict) else cat) or "")
        if not rec or not cat_id:
            missing.append("engine_catalog")
            continue
        name = source_cats.get(cat_id)
        if name is None:
            missing.append("engine_catalog")
        elif name not in target_cats:
            fixes.append(ref_entry("engine_catalog", f"{d.get('name') or d['id']} (catalog '{name}')",
                                   ["recommendation engine"], f"catalog '{name}' isn't in the target"))
    return fixes, sorted(set(missing))


# ---------- plan ----------

def conflict_override(text):
    dep, sep, action = text.partition("=")
    if not sep or not dep or not action:
        raise argparse.ArgumentTypeError("use DEP_ID=duplicate or DEP_ID=use_old")
    return dep.strip(), action.strip()


def preview_deps(path):
    data = raw_json(path)
    check_error(path, data)
    rec = data.get("result") if isinstance(data, dict) and isinstance(data.get("result"), dict) else data
    if not isinstance(rec, dict) or not isinstance(rec.get("dependencies"), list):
        fail(f"{path}: expected a preview_clone_scenario result with a dependencies list.")
    deps = []
    for d in rec["dependencies"]:
        if not isinstance(d, dict) or not d.get("id") or not d.get("type"):
            fail(f"{path}: a dependency has no id or type; save the preview again.")
        deps.append({"id": str(d["id"]), "type": str(d["type"]), "name": str(d.get("name") or "")[:120],
                     "exists": d.get("exists") is True, "changed": d.get("changed") is True})
    return deps, [redact(w) for w in rec.get("warnings") or []]


def scenario_names(path):
    data = load(path)
    recs = rows(data, "scenarios")
    if not recs and not isinstance(data, list):
        fail(f"{path}: expected a search_scenarios list of the target project.")
    return recs


def cmd_plan(a):
    for o in RULES["forbidden_on_conflict"]:
        for dep, action in a.on_conflict:
            if action == o:
                fail(f"--on-conflict {dep}={action}: {action} overwrites an existing item in the target project, which "
                     "can change live scenarios and campaigns that use it. This skill never uses it.")
    for dep, action in a.on_conflict:
        if action not in RULES["allowed_on_conflict"]:
            fail(f"--on-conflict {dep}={action}: use one of {', '.join(RULES['allowed_on_conflict'])}.")
    if a.source_project_id == a.project_id and a.source_project_name != a.project_name:
        fail("The source and target project IDs match but the names differ; check which project is which.")
    if a.source_project_id == a.project_id and norm(a.source_org) != norm(a.target_org):
        fail("The source and target project IDs match but the organisations differ; check which is which.")
    cross_org = norm(a.source_org) != norm(a.target_org)
    src = scenario_record(a.source, "the source scenario")
    deps, preview_warnings = preview_deps(a.preview)
    mode = "same_project" if a.source_project_id == a.project_id else "cross_project"
    source_id = str(src.get("_id") or src.get("id") or "")
    source_name = str(src.get("name") or "").strip()
    today = a.today or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    suffix = a.name_suffix if a.name_suffix is not None else RULES["name_suffix_format"].replace("{date}", today)
    final_name = source_name + suffix
    problems, warnings = [], []

    def block(check, message):
        problems.append({"check": check, "message": message})

    def warn(check, message):
        warnings.append({"check": check, "message": message})

    if cross_org and not a.cross_org_confirmed:
        block("cross_org_unconfirmed", f"The source is in organisation '{a.source_org}' and the target in '{a.target_org}'. "
              "Copying between organisations can move one client's flow, content and settings into another's project. "
              "Ask the user to confirm the cross-organisation copy in their own words, then pass --cross-org-confirmed.")

    by_id = {d["id"]: d for d in deps}
    unknown = sorted(dep for dep, _ in a.on_conflict if dep not in by_id)
    if unknown:
        fail(f"--on-conflict names IDs the preview doesn't list: {', '.join(unknown)}.")
    new = sorted(dep for dep, _ in a.on_conflict if not by_id[dep]["exists"])
    if new:
        fail(f"--on-conflict names dependencies the target doesn't have yet ({', '.join(new)}); on_conflict only "
             "applies to ones the preview says exist.")
    overrides = dict(a.on_conflict)
    scenario_dep = [d for d in deps if d["type"] == RULES["scenario_dependency_type"] and d["id"] == source_id]
    if not scenario_dep:
        block("preview_mismatch", "The preview doesn't list the source scenario itself; it may be for another "
              "scenario. Run preview_clone_scenario again for this scenario.")
    elif mode == "same_project" and not scenario_dep[0]["exists"]:
        block("stale_preview", "A copy within one project, but the preview doesn't say the scenario exists, so the plan "
              "can't send duplicate for it. Run preview_clone_scenario again and rebuild the plan.")
    if mode == "same_project":
        missing = sorted(d["id"] for d in deps if not d["exists"])
        if missing and scenario_dep and scenario_dep[0]["exists"]:
            block("stale_preview", "A copy within one project, but the preview says these dependencies don't exist in "
                  f"it: {', '.join(missing)}. Run preview_clone_scenario again and rebuild the plan.")
    if not src.get("nodes"):
        block("empty_source", "The source scenario has no steps.")
    if src.get("archived") is True:
        warn("archived_source", "The source scenario is archived.")
    if not suffix.strip():
        block("no_suffix", "The name suffix is empty. Give the clone a distinct name so it can be found again by name.")
    taken = sorted({str(r.get("_id") or r.get("id")) for r in scenario_names(a.target_scenarios)
                    if str(r.get("name") or "").strip() == final_name})
    if taken:
        block("name_taken", f"The target already has {len(taken)} scenario(s) named '{final_name}'. Choose another "
              "suffix: the clone must have a name no other scenario has.")

    items, creates, reuses, copies = [], [], [], []
    for d in sorted(deps, key=lambda x: (x["type"] != RULES["scenario_dependency_type"], x["type"], x["id"])):
        item = {"id": d["id"], "type": d["type"]}
        is_scenario = d["type"] == RULES["scenario_dependency_type"] and d["id"] == source_id
        label = {"id": d["id"], "type": d["type"], "name": d["name"]}
        if d["exists"]:
            default = RULES["scenario_on_conflict"] if is_scenario else RULES["dependency_on_conflict"]
            action = overrides.get(d["id"], default)
            if is_scenario and action != RULES["scenario_on_conflict"]:
                fail(f"--on-conflict {d['id']}: the scenario itself is always duplicated, so the source stays as it is.")
            item["on_conflict"] = action
            if action == "use_old":
                reuses.append(label)
                if d["changed"] and mode == "cross_project":
                    warn("dependency_differs", f"The target's {d['type']} '{d['name']}' differs from the source's. The "
                         "clone uses the target's version; pass --on-conflict ID=duplicate to copy the source's "
                         "version as a new item instead.")
            elif not is_scenario:
                copies.append(label)
                warn("duplicate_dependency", f"Creates a second {d['type']} '{d['name']}' in the target.")
        else:
            creates.append(label)
        items.append(item)
    new_count = len([c for c in creates if c["type"] != RULES["scenario_dependency_type"]]) + len(copies)
    if new_count > RULES["new_dependency_warning"]:
        warn("many_new_items", f"The clone also creates {new_count} new items in the target, besides the scenario.")
    if preview_warnings:
        warn("preview_warnings", f"The preview returned {len(preview_warnings)} mapping warning(s): "
             + "; ".join(preview_warnings[:5]))

    hooks = webhooks(src)
    if hooks and cross_org:
        block("cross_org_webhooks", f"{len(hooks)} webhook step(s), and the target is in another organisation. Cloning "
              "would copy their headers and body, which often hold one client's API tokens, into another client's "
              "project. Remove or replace the webhooks in the source first, or choose another source.")
    elif hooks:
        warn("webhook_tokens", f"{len(hooks)} webhook step(s). Cloning copies their headers and body, which often hold "
             "API tokens, so the token is then stored in the clone too. Check with the webhook's owner that the "
             "target may use it, and review each webhook in the Engagement UI before switching the clone on.")
    senders = [n for n in src.get("nodes") or [] if isinstance(n, dict) and type_has(n, RULES["sender_type_words"])]
    if senders and mode == "cross_project":
        warn("sender_defaults", f"{len(senders)} email or SMS step(s). Their sender and channel settings come from the "
             "target project's defaults; check each step in the Engagement UI.")

    refs = collect_refs(src)
    fixes, not_checked = check_refs(refs, a, set(by_id), mode)
    efix, emissing = engine_catalog_fixes(a, deps)
    fixes = sorted(fixes + efix, key=lambda f: ({"high": 0, "medium": 1, "low": 2}.get(f["priority"], 3), f["kind"],
                                                  str(f["ref"])))
    not_checked = sorted(set(not_checked) | set(emissing))
    if not_checked:
        warn("not_checked", "Not checked against the target (look-up not given): " + ", ".join(not_checked) + ".")

    payload = {"source_project_id": a.source_project_id, "target_project_id": a.project_id, "items": items,
               "name_suffix": suffix, "use_mapping": True, "use_project_defaults": True}
    if a.initiative_id:
        payload["target_initiative_id"] = a.initiative_id
    after = dict(shape(src), status="draft", name=final_name, webhook_count=len(hooks))
    status = "blocked" if problems else "ready"
    ch = {"n": 1, "status": status, "kind": "create",
          "target": f"draft scenario '{final_name}', cloned from '{source_name}'",
          "tool": "clone_scenario", "payload": payload, "before": None, "after": after,
          "creates": creates, "copies": copies, "reuses": reuses,
          "undo": [], "undo_note": "This skill never deletes. To remove the clone, delete the scenario (and any new "
          "items listed under creates and copies that nothing else uses) in the Engagement UI.",
          "live_impact": "none",
          "impact_note": "None: clone_scenario creates the scenario as a draft and never starts it. New dependencies "
                         "(aggregates, expressions, engines) are created in the target but nothing uses them until "
                         "someone switches the clone on.",
          "problems": problems, "warnings": warnings}
    high = len([f for f in fixes if f["priority"] == "high"])
    summary = {"source": f"'{source_name}' in {a.source_project_name}", "target_project": a.project_name,
               "source_org": a.source_org, "target_org": a.target_org, "cross_org": cross_org,
               "mode": mode, "clone_name": final_name, "steps": after["node_count"],
               "creates": len(creates), "copies": len(copies), "reuses": len(reuses),
               "fixes": len(fixes), "high_priority_fixes": high, "webhooks": len(hooks)}
    return {"ok": True, "project_id": a.project_id, "project_name": a.project_name,
            "source_project_id": a.source_project_id, "source_project_name": a.source_project_name,
            "source_org": a.source_org, "target_org": a.target_org, "cross_org": cross_org,
            "source_scenario_id": source_id, "source_scenario_name": source_name, "mode": mode,
            "changes": [ch], "batches": [[1]] if status == "ready" else [],
            "fix_list": fixes, "not_checked": not_checked, "webhooks": hooks, "summary": summary,
            "counts": {"ready": int(status == "ready"), "blocked": int(status == "blocked"), "no_change": 0}}


# ---------- find ----------

def read_plan(path):
    plan = raw_json(path)
    if not isinstance(plan, dict) or not isinstance(plan.get("changes"), list) or not plan["changes"]:
        fail(f"{path}: not a plan file (no changes list). Use the file that scenario_clone_plan.py plan wrote.")
    return plan


def created_at(rec):
    try:
        return float(rec.get("created"))
    except (TypeError, ValueError):
        return None


def cmd_find(a):
    plan = read_plan(a.plan)
    want = str(plan["changes"][0].get("after", {}).get("name") or "")
    source = str(plan.get("source_scenario_name") or "")
    found = []
    for r in scenario_names(a.scenarios):
        name = str(r.get("name") or "").strip()
        when = created_at(r)
        exact = name == want
        recent = a.since is not None and when is not None and when >= a.since and source and source in name
        if exact or recent:
            found.append({"id": str(r.get("_id") or r.get("id")), "name": name, "status": r.get("status"),
                          "created": when, "match": "exact_name" if exact else "created_since"})
    found.sort(key=lambda f: (f["match"] != "exact_name", -(f["created"] or 0), f["id"]))
    state = "none" if not found else ("one" if len(found) == 1 else "several")
    nxt = {"none": "No clone found. It's safe to call clone_scenario again only after the user confirms again.",
           "one": "The clone exists: don't clone again. Read it back with search_scenarios and run verify.",
           "several": "More than one match: don't clone again. Show the user the matches and ask which is the clone."}
    return {"ok": True, "planned_name": want, "state": state, "found": found, "next": nxt[state]}


# ---------- verify ----------

def numbered_file(text):
    """N=FILE, split on the first "=": a plan change number and its read-back file."""
    n, sep, path = text.partition("=")
    if not sep or not path:
        raise argparse.ArgumentTypeError("use N=FILE, e.g. 1=readback.json")
    try:
        return int(n), path
    except ValueError:
        raise argparse.ArgumentTypeError(f"{n!r} isn't a change number")


def cmd_verify(a):
    plan = read_plan(a.plan)
    by_n = {ch.get("n"): ch for ch in plan["changes"] if isinstance(ch, dict)}
    results = []
    for n, path in sorted(dict(a.readback).items()):
        ch = by_n.get(n)
        if ch is None or ch.get("status") != "ready":
            fail(f"--readback {n}: the plan has no ready change {n}.")
        want = ch.get("after") or {}
        res = {"n": n, "kind": ch.get("kind"), "target": ch.get("target")}
        data = raw_json(path)
        err = check_error(path, data, not_found_ok=True)
        if err is not None:
            res.update(state="not_in_place", note=f"The scenario wasn't found ({err}). Before cloning again, run find: "
                       "a clone that errored may still have been made.")
            results.append(res)
            continue
        rec = unwrap(data)
        if not isinstance(rec, dict) or not isinstance(rec.get("nodes"), list):
            fail(f"{path}: expected one search_scenarios scenario_id detail of the clone.")
        have = dict(shape(rec), status=rec.get("status"), name=str(rec.get("name") or "").strip(),
                    webhook_count=len(webhooks(rec)))
        mismatches = [{"field": k, "planned": want.get(k), "found": have[k]} for k in sorted(have)
                      if k in want and k != "status" and want.get(k) != have[k]]
        res["scenario_id"] = str(rec.get("_id") or rec.get("id") or "")
        if str(rec.get("_id") or rec.get("id") or "") == str(plan.get("source_scenario_id") or ""):
            mismatches.append({"field": "scenario_id", "planned": "a new scenario", "found": "the source scenario"})
        status = str(have["status"] or "").lower()
        if status not in RULES["not_started_statuses"]:
            res["alert"] = (f"The clone's status is {have['status']!r}, not draft. Tell the user at once; this skill never "
                            "starts scenarios, and it must be stopped in the Engagement UI.")
            mismatches.append({"field": "status", "planned": "draft", "found": have["status"]})
        res["state"] = "not_in_place" if mismatches else "in_place"
        if mismatches:
            res["mismatches"] = mismatches
        results.append(res)
    unchecked = sorted(n for n, ch in by_n.items() if ch.get("status") == "ready" and n not in dict(a.readback))
    return {"ok": True, "results": results, "not_checked": unchecked,
            "next": "Fix the references in the plan's fix_list, then run scenario-qa on the clone before anyone "
                    "switches it on. Edits go through engagement-scenario-builder."}


def write_out(path, text):
    if path:
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"{path}: can't write it ({e}).")


def unix_seconds(text):
    try:
        return float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} isn't a Unix time in seconds")


def iso_date(text):
    try:
        return datetime.date.fromisoformat(text).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} isn't a date (YYYY-MM-DD)")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # scenario names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="build the clone plan and the fix list")
    p.add_argument("--source", required=True, help="search_scenarios scenario_id detail of the source (include_node_designs=true)")
    p.add_argument("--preview", required=True, help="saved preview_clone_scenario result")
    p.add_argument("--source-project-id", required=True, help="the source project's ID")
    p.add_argument("--source-project-name", required=True, help="the source project's name, shown in the plan")
    p.add_argument("--project-id", required=True, help="the target project ID the user confirmed")
    p.add_argument("--project-name", required=True, help="the target project's name, shown in the plan")
    p.add_argument("--source-org", required=True, help="the source project's organisation (name or ID)")
    p.add_argument("--target-org", required=True, help="the target project's organisation (name or ID, same form as --source-org)")
    p.add_argument("--cross-org-confirmed", action="store_true",
                   help="set only after the user confirmed, in their own words, a copy between two organisations")
    p.add_argument("--target-scenarios", required=True, help="search_scenarios list of the target project (archived=null)")
    p.add_argument("--name-suffix", default=None,
                   help="suffix appended to the clone's name (default: name_suffix_format in references/rules.json)")
    p.add_argument("--today", type=iso_date, default=None, help="date for the default suffix, YYYY-MM-DD (default: today in UTC)")
    p.add_argument("--on-conflict", action="append", type=conflict_override, default=[],
                   help="DEP_ID=duplicate|use_old for a dependency that exists in the target (repeat); replace is refused")
    p.add_argument("--target-events", help="saved get_event_schema of the target")
    p.add_argument("--target-properties", help="saved get_customer_property_schema of the target")
    p.add_argument("--target-consent", help="saved get_consent_settings of the target")
    p.add_argument("--target-frequency-policies", help="saved get_frequency_policies of the target")
    p.add_argument("--target-integrations", help="saved search_integrations list of the target")
    p.add_argument("--target-catalogs", help="saved search_catalogs list of the target")
    p.add_argument("--target-variables", help="saved list_project_variables of the target")
    p.add_argument("--source-recommendations", action="append", default=[],
                   help="saved search_recommendations detail from the source for an engine the clone creates (repeat)")
    p.add_argument("--source-catalogs", help="saved search_catalogs list of the source project")
    p.add_argument("--initiative-id", help="optional target initiative ID")
    p.add_argument("--out", help="also write the plan to this file")
    f = sub.add_parser("find", help="look for the clone in the target before cloning again")
    f.add_argument("--plan", required=True, help="the plan file from the plan step")
    f.add_argument("--scenarios", required=True, help="search_scenarios list of the target project")
    f.add_argument("--since", type=unix_seconds, default=None,
                   help="Unix seconds just before the clone call: also match scenarios created since then")
    f.add_argument("--out", help="also write the result to this file")
    v = sub.add_parser("verify", help="check the clone's read-back")
    v.add_argument("--plan", required=True, help="the plan file from the plan step")
    v.add_argument("--readback", action="append", type=numbered_file, required=True,
                   help="N=FILE: the search_scenarios scenario_id detail of the clone after change N")
    v.add_argument("--out", help="also write the result to this file")
    a = ap.parse_args()
    out = {"plan": cmd_plan, "find": cmd_find, "verify": cmd_verify}[a.cmd](a)
    text = json.dumps(out, indent=2, ensure_ascii=False, sort_keys=False)
    write_out(a.out, text)
    print(text)


if __name__ == "__main__":
    main()
