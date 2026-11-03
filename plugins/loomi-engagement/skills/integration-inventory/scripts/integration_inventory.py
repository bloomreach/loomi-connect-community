#!/usr/bin/env python3
"""Inventory Bloomreach Engagement integrations, API triggers, project variables and scenario webhook steps.

Usage:
  python3 integration_inventory.py [--integrations integrations.json] [--api-triggers triggers.json]
         [--api-trigger-detail trigger_<id>.json ...] [--variables variables.json]
         [--assets KIND=FILE ...] [--denied NAME ...] [--out inventory.json]

--integrations        saved search_integrations list (id, name and type).
--api-triggers        saved search_api_triggers list.
--api-trigger-detail  saved search_api_triggers detail for one trigger (event_type, properties, scenario_ids).
--variables           saved list_project_variables response.
--assets              KIND=FILE, where KIND is scenario, email, sms, banner or in_app_message: a saved list (for
                      statuses) or detail (for definitions). Scenario details are where webhook steps live.
--denied              a tool or asset kind that returned HTTP 403 (integrations, api_triggers, variables, scenario,
                      email, sms, banner, in_app_message), reported as "not checked (no access)".

Prints JSON: each integration, API trigger and project variable with what references it, every webhook step
described (method, host, how it authenticates), and findings sorted by priority (high, medium, low): unused,
duplicated, disabled or misconfigured items, credentials stored in variables, URLs or step headers, webhook steps
pointing at integrations that don't exist, and templates that use variables that don't exist.

It never prints a secret: no variable values, header values, request bodies, full URLs or query strings. Values are
described ("looks like a key", "a URL on <host>"), and URLs are reduced to their host. Rules are in
references/rules.json. Standard library only; no network.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

RULES_PATH = Path(__file__).resolve().parent.parent / "references" / "rules.json"
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
SKIP_KEYS = {"created_by_display_name", "edited_by_display_name"}
TOKEN = re.compile(r"[A-Za-z0-9_\-]+")
URL = re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s\"'<>]+", re.I)
VAR_REF = re.compile(r"project_variables?\s*(?:\.\s*([A-Za-z_][A-Za-z0-9_]*)|\[\s*['\"]([^'\"]+)['\"]\s*\])")
TEMPLATED = re.compile(r"\{\{|\{%|\[\[")


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
    return [r for r in data if isinstance(r, dict)]


def rid(r):
    for k in ("_id", "id"):
        if r.get(k) not in (None, ""):
            return str(r[k])
    return None


def strings(node):
    if isinstance(node, dict):
        for k in sorted(node, key=str):
            if k in SKIP_KEYS:
                continue
            yield from strings(node[k])
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)
    elif isinstance(node, str):
        yield node


class Rules:
    def __init__(self, raw):
        self.raw = raw
        self.live = {s.lower() for s in raw["live_statuses"]}
        self.secret_values = [re.compile(p) for p in raw["secret_value_patterns"]]
        self.safe_values = [re.compile(p, re.I) for p in raw["safe_value_patterns"]]
        words = sorted(raw["secret_words"], key=len, reverse=True)
        self.secret_name = re.compile(r"(?<![a-z])(?:" + "|".join(re.escape(w) for w in words) + r")(?![a-z])")
        tests = sorted(raw["test_words"], key=len, reverse=True)
        self.test_name = re.compile(r"(?<![a-z])(?:" + "|".join(re.escape(w) for w in tests) + r")(?![a-z])")

    def looks_secret_value(self, value):
        v = str(value).strip()
        if any(p.search(v) for p in self.safe_values):
            return False
        return any(p.search(v) for p in self.secret_values)

    def secret_named(self, name):
        return bool(name) and bool(self.secret_name.search(camel_split(str(name))))

    def test_named(self, name):
        return bool(name) and bool(self.test_name.search(str(name).lower()))

    def group(self, itype):
        t = str(itype or "").lower()
        for group, needles in self.raw["type_groups"].items():
            if any(n in t for n in needles):
                return group
        return "other"


def camel_split(text):
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text).lower()


def host_of(url):
    """(scheme, host) of a URL, or (None, None). Hosts with template code are reported as templated."""
    try:
        parts = urlsplit(str(url).strip())
    except ValueError:
        return None, None
    netloc = parts.netloc.rsplit("@", 1)[-1]
    if TEMPLATED.search(netloc):
        return parts.scheme or None, "(templated host)"
    host = (parts.hostname or "").strip()
    return (parts.scheme or None), (host or None)


def redact(text, rules):
    """Names are printed; strip anything URL- or key-shaped from them first."""
    if text is None:
        return None

    def url_sub(m):
        scheme, host = host_of(m.group(0))
        return f"{scheme}://{host}/..." if host else "[url]"

    out = URL.sub(url_sub, str(text))
    return " ".join("[redacted]" if len(w) >= 16 and rules.looks_secret_value(w) else w for w in out.split(" "))


def describe_value(value, rules):
    v = "" if value is None else str(value)
    if not v.strip():
        return "empty"
    if rules.looks_secret_value(v):
        return "looks like a key"
    if re.fullmatch(r"(?i)true|false|yes|no|on|off", v.strip()):
        return "boolean"
    if re.fullmatch(r"-?\d+(?:\.\d+)?", v.strip()):
        return "number"
    if re.fullmatch(r"[0-9a-f]{24}", v.strip()):
        return "an object ID"
    if URL.fullmatch(v.strip()):
        _, host = host_of(v)
        return f"a URL on {host}" if host else "a URL"
    if "@" in v and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v.strip()):
        return "an email address"
    return "text"


def norm_name(name):
    n = str(name or "").lower()
    n = re.sub(r"\((?:new|copy|old|\d+)\)|\bcopy of\b|\bv\d+\b|\bnew\b", " ", n)
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


class Inventory:
    def __init__(self, rules):
        self.rules = rules
        self.findings = []

    def add(self, priority, area, item, issue, action):
        self.findings.append({"priority": priority, "area": area, "item": redact(item, self.rules),
                              "issue": issue, "action": action})


def header_list(h):
    """[(name, value)] from a headers list or dict, whatever its shape."""
    out = []
    if isinstance(h, dict):
        out = [(k, v) for k, v in h.items()]
    elif isinstance(h, list):
        for e in h:
            if isinstance(e, dict):
                name = e.get("name") or e.get("key") or e.get("header")
                out.append((name, e.get("value")))
            elif isinstance(e, (list, tuple)) and len(e) == 2:
                out.append((e[0], e[1]))
    return [(str(k), "" if v is None else str(v)) for k, v in out if k]


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character; Windows consoles default to cp1252
    p = argparse.ArgumentParser(description="Inventory Engagement integrations, API triggers, project variables and webhooks.")
    p.add_argument("--integrations")
    p.add_argument("--api-triggers")
    p.add_argument("--api-trigger-detail", action="append", default=[])
    p.add_argument("--variables")
    p.add_argument("--assets", action="append", default=[], metavar="KIND=FILE")
    p.add_argument("--denied", action="append", default=[], metavar="NAME")
    p.add_argument("--rules", default=str(RULES_PATH), help="rules file (default: the skill's references/rules.json)")
    p.add_argument("--out", help="also write the JSON to this file")
    a = p.parse_args()

    raw = load_json(a.rules, "rules")
    if not isinstance(raw, dict) or "secret_words" not in raw:
        fail(f"{a.rules}: not a rules file.")
    rules = Rules(raw)
    inv = Inventory(rules)
    denied = sorted({d.strip().lower() for d in a.denied})
    if not any([a.integrations, a.api_triggers, a.api_trigger_detail, a.variables]):
        fail("give at least one of --integrations, --api-triggers, --api-trigger-detail or --variables.")

    # Assets: merge list records (status) and details (definitions) by kind and id.
    assets = {}
    asset_counts = {}
    for pair in a.assets:
        if "=" not in pair:
            fail(f"--assets {pair!r}: expected KIND=FILE.")
        kind, path = pair.split("=", 1)
        kind = kind.strip().lower()
        if kind not in raw["asset_kinds"]:
            fail(f"--assets {pair!r}: unknown kind {kind!r}. Use one of: {', '.join(raw['asset_kinds'])}.")
        for r in records(path.strip()):
            oid = rid(r) or r.get("name")
            if not oid:
                continue
            key = (kind, str(oid))
            entry = assets.setdefault(key, {"kind": kind, "id": str(oid), "name": None, "status": None,
                                            "archived": False, "docs": []})
            entry["name"] = entry["name"] or r.get("name")
            status = r.get("status")
            if status is None and isinstance(r.get("enabled"), bool):
                status = "active" if r["enabled"] else "inactive"
            if status is not None:
                entry["status"] = str(status)
            if r.get("archived") is True:
                entry["archived"] = True
            if any(k in r for k in ("nodes", "customer_filter", "variants", "action", "design", "content", "trigger",
                                    "subject", "html")):
                entry["docs"].append(r)
        asset_counts[kind] = sum(1 for k in assets if k[0] == kind)

    def live(entry):
        if entry["archived"]:
            return False
        if entry["status"] is None:
            return None
        return entry["status"].lower() in rules.live

    for e in assets.values():
        blob_items = [s for d in e["docs"] for s in strings(d)]
        e["tokens"] = set(TOKEN.findall("\n".join(blob_items)))
        e["var_refs"] = set()
        for s in blob_items:
            for m in VAR_REF.finditer(s):
                e["var_refs"].add(m.group(1) or m.group(2))

    def ref_row(e, how):
        return {"kind": e["kind"], "id": e["id"], "name": redact(e["name"], rules), "status": e["status"],
                "live": live(e), "how": how}

    defs_checked = sum(1 for e in assets.values() if e["docs"])

    # ---------------------------------------------------------------- integrations
    integrations = []
    known_integrations = {}
    if a.integrations:
        for r in records(a.integrations):
            iid = rid(r)
            if not iid:
                continue
            known_integrations[iid] = r
    # ---------------------------------------------------------------- webhook steps
    webhooks = []
    marker = raw["webhook_node_marker"].lower()
    int_refs = {}
    for key in sorted(assets):
        e = assets[key]
        for doc in e["docs"]:
            for node in doc.get("nodes") or []:
                if not isinstance(node, dict) or marker not in str(node.get("type", "")).lower():
                    continue
                pp = node.get("parametrized_parts") if isinstance(node.get("parametrized_parts"), dict) else {}
                url = pp.get("url") or node.get("url") or ""
                scheme, host = host_of(url)
                headers = header_list(pp.get("headers") if pp.get("headers") else node.get("headers"))
                auth_headers = [n for n, _ in headers if n.lower() in ("authorization", "proxy-authorization")
                                or rules.secret_named(n)]
                plain_auth = [n for n, v in headers if n in auth_headers and v.strip() and not TEMPLATED.search(v)]
                query = []
                try:
                    query = parse_qsl(urlsplit(str(url)).query, keep_blank_values=True)
                except ValueError:
                    pass
                secret_params = [(k, v) for k, v in query if rules.secret_named(k)]
                fixed_secret = sorted({k for k, v in secret_params if v.strip() and not TEMPLATED.search(v)})
                empty_secret = sorted({k for k, v in secret_params if not v.strip()})
                iid = node.get("auth_integration_id")
                auth = []
                if iid:
                    integ = known_integrations.get(str(iid))
                    auth.append(f"the authentication integration {redact(integ.get('name'), rules)!r}" if integ
                                else "an authentication integration that wasn't found")
                    int_refs.setdefault(str(iid), []).append(ref_row(e, "webhook authentication"))
                if node.get("use_basic_auth"):
                    auth.append("basic auth")
                if auth_headers:
                    auth.append("an auth header" if len(auth_headers) == 1 else f"{len(auth_headers)} auth headers")
                if fixed_secret or empty_secret:
                    auth.append("a credential parameter in the URL")
                where = f"{redact(e['name'], rules) or e['id']} / step {node.get('id')}"
                desc = (f"an HTTP {str(node.get('method') or 'request').upper()} to "
                        f"{host or 'an unreadable URL'}" + (" over plain HTTP" if scheme == "http" else "")
                        + (" with " + " and ".join(auth) if auth else " with no authentication"))
                flags = []
                is_live = live(e)
                if iid and known_integrations and str(iid) not in known_integrations:
                    flags.append("integration not found")
                    inv.add("high" if is_live else "medium", "webhook", where,
                            "Webhook step authenticates with an integration that doesn't exist (deleted or from "
                            "another project)", "Pick an existing authentication integration in the step, or "
                            "recreate it in Project settings > Integrations")
                if fixed_secret:
                    flags.append("credential in URL")
                    inv.add("high" if is_live else "medium", "webhook", where,
                            f"A credential is written into the URL query string ({', '.join(fixed_secret)}); it's "
                            "copied with the scenario and appears in logs", "Move it to an authentication "
                            "integration or a header, and rotate it")
                if empty_secret:
                    flags.append("empty credential parameter")
                    inv.add("high" if is_live else "medium", "webhook", where,
                            f"The URL has an empty credential parameter ({', '.join(empty_secret)}), so calls will "
                            "be rejected", "Fill in the step's credential parameter (or use an integration)")
                if plain_auth:
                    flags.append("credential in step headers")
                    inv.add("low", "webhook", where, "An auth header holds a credential in plain text in the step, "
                            "so every copy of the scenario carries it", "Prefer an authentication integration")
                if scheme == "http":
                    flags.append("plain HTTP")
                    inv.add("medium", "webhook", where, "Sends customer data over plain HTTP", "Switch the URL to HTTPS")
                if not host:
                    flags.append("no valid URL")
                    inv.add("high" if is_live else "medium", "webhook", where, "The step has no valid URL",
                            "Set the endpoint URL")
                webhooks.append({"asset_kind": e["kind"], "asset_id": e["id"], "asset": redact(e["name"], rules),
                                 "status": e["status"], "live": is_live, "step_id": node.get("id"),
                                 "step": redact(node.get("name"), rules),
                                 "method": str(node.get("method") or "").upper() or None, "host": host,
                                 "authentication": auth or ["none"], "description": desc, "flags": flags})

    if a.integrations:
        by_norm = {}
        for iid in sorted(known_integrations, key=lambda k: (str(known_integrations[k].get("name")), k)):
            r = known_integrations[iid]
            name, itype = r.get("name"), r.get("type")
            group = rules.group(itype)
            refs = list(int_refs.get(iid, []))
            for e in assets.values():
                if iid in e["tokens"] and not any(x["id"] == e["id"] and x["kind"] == e["kind"] for x in refs):
                    refs.append(ref_row(e, "ID in definition"))
            refs.sort(key=lambda x: (x["kind"], x["name"] or "", x["id"]))
            flags = []
            label = f"{name or iid} ({itype or 'no type'})"
            by_norm.setdefault((str(itype).lower(), norm_name(name)), []).append(iid)
            enabled = r.get("enabled")
            state = str(r.get("status") or r.get("state") or "").lower()
            if enabled is False or state in ("disabled", "inactive", "error", "failed", "invalid"):
                flags.append("disabled or failing")
                used_live = any(x["live"] for x in refs)
                inv.add("high" if used_live else "medium", "integration", label,
                        f"Integration is {state or 'disabled'}" + (", and a live asset uses it" if used_live else ""),
                        "Fix the connection in Project settings > Integrations, or remove it if nothing needs it")
            if not name or not itype or norm_name(name) in ("", "untitled", "untitled integration"):
                flags.append("incomplete")
                inv.add("low", "integration", label, "Integration has no proper name or type",
                        "Name it after what it connects to, or remove it")
            if rules.test_named(name):
                flags.append("test name")
                inv.add("low", "integration", label, "Named like a test or throwaway integration",
                        "Confirm with the owner and remove it if it's not needed")
            if group in raw["usage_visible_groups"] and not refs and defs_checked:
                flags.append("no reference found")
                inv.add("medium", "integration", label,
                        f"No reference found in the {defs_checked} scenario, campaign and weblayer definitions checked",
                        "Check its usage in the UI before removing it; it may be used by assets not checked")
            integrations.append({"id": iid, "name": redact(name, rules), "type": itype, "group": group,
                                 "references": refs, "flags": flags})
        for (itype, n), ids in sorted(by_norm.items()):
            if len(ids) > 1:
                names = sorted({str(known_integrations[i].get("name")) for i in ids})
                for i in ids:
                    next(x for x in integrations if x["id"] == i)["flags"].append("duplicate")
                inv.add("medium", "integration", " / ".join(names) + f" ({itype})",
                        f"{len(ids)} integrations of the same type with the same or near-identical names",
                        "Find out which one imports, exports or sends use, then remove the others")
        groups = {}
        for x in integrations:
            if x["group"] == "channel":
                groups.setdefault(str(x["type"]).lower(), []).append(x)
        for itype, xs in sorted(groups.items()):
            if len(xs) > 1 and not all("duplicate" in x["flags"] for x in xs):
                inv.add("low", "integration", f"{len(xs)} {itype} integrations",
                        "Several delivery integrations of the same type", "Confirm which one is the project default "
                        "and whether the others are still needed")

    # ---------------------------------------------------------------- API triggers
    triggers = {}
    if a.api_triggers:
        for r in records(a.api_triggers):
            tid = rid(r)
            if tid:
                triggers[tid] = {"list": r, "detail": None}
    for path in a.api_trigger_detail:
        for r in records(path):
            tid = rid(r)
            if tid:
                triggers.setdefault(tid, {"list": r, "detail": None})["detail"] = r
    scenario_ids = {k[1] for k in assets if k[0] == "scenario"}
    trigger_rows = []
    by_name, by_event = {}, {}
    for tid in sorted(triggers, key=lambda k: (str((triggers[k]["detail"] or triggers[k]["list"]).get("name")), k)):
        t = triggers[tid]
        rec = t["detail"] or t["list"]
        name = rec.get("name")
        label = name or tid
        archived = bool(rec.get("archived"))
        flags, listeners = [], []
        by_name.setdefault(norm_name(name), []).append(tid)
        for e in sorted(assets.values(), key=lambda x: (x["kind"], x["id"])):
            if tid in e["tokens"]:
                listeners.append(ref_row(e, "ID in definition"))
        d = t["detail"]
        if d is not None:
            for sid in d.get("scenario_ids") or []:
                e = assets.get(("scenario", str(sid)))
                if e:
                    if not any(x["id"] == e["id"] for x in listeners):
                        listeners.append(ref_row(e, "listed by the trigger"))
                else:
                    listeners.append({"kind": "scenario", "id": str(sid), "name": None, "status": None, "live": None,
                                      "how": "listed by the trigger"})
                    if scenario_ids:
                        flags.append("listener not found")
                        inv.add("medium", "api_trigger", label, "Lists a scenario that isn't in the saved scenario "
                                "list (archived or deleted)", "Check the scenario in the UI; re-point or remove the trigger")
            event = d.get("event_type")
            if event:
                by_event.setdefault(str(event), []).append(tid)
            else:
                flags.append("no event type")
                live_l = any(x["live"] for x in listeners)
                inv.add("high" if live_l else "medium", "api_trigger", label,
                        "Doesn't set the event type it fires" + (", and a live scenario listens to it" if live_l else ""),
                        "Set the event type in the trigger, or remove the trigger if it's unused")
        listeners.sort(key=lambda x: (x["kind"], x["name"] or "", x["id"]))
        live_listeners = [x for x in listeners if x["live"]]
        if archived and live_listeners:
            flags.append("archived but used")
            inv.add("high", "api_trigger", label, "Archived, but a live scenario listens to it",
                    "Unarchive it or move the scenario to another trigger")
        elif d is not None and not listeners:
            flags.append("unused")
            inv.add("medium", "api_trigger", label, "Nothing listens to it: no scenario uses this trigger",
                    "Check whether an external system still calls it, then remove it")
        elif listeners and not live_listeners and all(x["live"] is False for x in listeners):
            flags.append("only inactive listeners")
            inv.add("medium", "api_trigger", label, "Only draft or inactive scenarios listen to it, so calls do nothing",
                    "Activate the scenario, or stop the external calls and remove the trigger")
        elif d is None and not listeners:
            flags.append("usage unknown")
            inv.add("low", "api_trigger", label, "Detail not fetched and no scenario definition mentions it",
                    "Fetch the trigger by ID to see which scenarios listen to it")
        if rules.test_named(name):
            flags.append("test name")
            inv.add("low", "api_trigger", label, "Named like a test or never named", "Rename it or remove it")
        trigger_rows.append({"id": tid, "name": redact(name, rules), "archived": archived,
                             "event_type": (d or {}).get("event_type") if d is not None else None,
                             "payload_properties": len((d or {}).get("properties") or []) if d is not None else None,
                             "listeners": listeners, "flags": flags})
    for n, ids in sorted(by_name.items()):
        if len(ids) > 1 and n:
            inv.add("medium", "api_trigger", " / ".join(sorted(str((triggers[i]["detail"] or triggers[i]["list"]).get("name")) for i in ids)),
                    f"{len(ids)} API triggers with the same name", "Keep one; point callers and scenarios at it")
    for ev, ids in sorted(by_event.items()):
        if len(ids) > 1:
            inv.add("low", "api_trigger", f"event {ev}", f"{len(ids)} API triggers fire the same event type",
                    "Check whether one would do")

    # ---------------------------------------------------------------- project variables
    variable_rows = []
    defined = set()
    if a.variables:
        recs = records(a.variables)
        by_ref, by_value = {}, {}
        for r in sorted(recs, key=lambda x: str(x.get("reference") or x.get("name") or "")):
            ref = str(r.get("reference") or r.get("name") or "").strip()
            if not ref:
                continue
            defined.add(ref)
            value = r.get("value")
            vdesc = describe_value(value, rules)
            refs = sorted((ref_row(e, "template") for e in assets.values() if ref in e["var_refs"]),
                          key=lambda x: (x["kind"], x["name"] or "", x["id"]))
            flags = []
            by_ref.setdefault(re.sub(r"[^a-z0-9]", "", ref.lower()), []).append(ref)
            if vdesc not in ("empty", "boolean", "number"):
                by_value.setdefault(str(value).strip(), []).append(ref)
            secret_name = rules.secret_named(ref) or rules.secret_named(r.get("description"))
            if vdesc == "looks like a key" or (secret_name and vdesc == "text"):
                flags.append("stored credential")
                inv.add("high", "variable", ref, "Holds a value that looks like a credential. Project variables "
                        "render into any template and anyone who edits templates can read them",
                        "Move the credential to an authentication integration (webhooks) and rotate it")
            elif secret_name:
                flags.append("credential name, empty")
                inv.add("low", "variable", ref, "Named like a credential but empty", "Remove it if nothing needs it")
            live_refs = [x for x in refs if x["live"]]
            if vdesc == "empty" and refs:
                flags.append("empty but used")
                inv.add("high" if live_refs else "medium", "variable", ref,
                        f"Empty, but {len(refs)} template(s) use it" + (", including live ones" if live_refs else ""),
                        "Set its value, or remove it from the templates")
            elif vdesc == "empty" and defs_checked:
                flags.append("empty and unused")
                inv.add("low", "variable", ref, "Empty, and no checked template uses it", "Remove it")
            elif not refs and defs_checked and "stored credential" not in flags:
                flags.append("no reference found")
                inv.add("low", "variable", ref, f"Not used in the {defs_checked} definitions checked",
                        "Check other templates (blocks, snippets) before removing it")
            if rules.test_named(ref):
                flags.append("test name")
            variable_rows.append({"reference": ref, "value": vdesc,
                                  "has_description": bool(str(r.get("description") or "").strip()),
                                  "references": refs, "flags": flags})
        for k, refs in sorted(by_ref.items()):
            if len(refs) > 1:
                inv.add("medium", "variable", " / ".join(sorted(refs)), "Variables whose names differ only in case or "
                        "punctuation; templates may use the wrong one", "Keep one and update the templates")
        for _, refs in sorted(by_value.items()):
            if len(refs) > 1:
                inv.add("low", "variable", " / ".join(sorted(refs)), "Same value in several variables",
                        "Keep one and update the templates")
        missing = {}
        for e in assets.values():
            for ref in e["var_refs"] - defined:
                missing.setdefault(ref, []).append(e)
        for ref in sorted(missing):
            es = missing[ref]
            is_live = any(live(e) for e in es)
            inv.add("high" if is_live else "medium", "variable", ref,
                    f"Used in {len(es)} template(s) but not defined, so it renders empty"
                    + (" in a live asset" if is_live else ""), "Create the variable or fix the reference")

    inv.findings.sort(key=lambda f: (PRIORITY_ORDER[f["priority"]], f["area"], f["item"] or "", f["issue"]))
    counts = {p: sum(1 for f in inv.findings if f["priority"] == p) for p in PRIORITY_ORDER}
    out = {
        "ok": True,
        "checked": {"integrations": len(known_integrations) if a.integrations else None,
                    "api_triggers": len(triggers) if (a.api_triggers or a.api_trigger_detail) else None,
                    "api_trigger_details": sum(1 for t in triggers.values() if t["detail"] is not None),
                    "variables": len(variable_rows) if a.variables else None,
                    "assets": {k: {"records": asset_counts.get(k, 0),
                                   "with_definitions": sum(1 for e in assets.values() if e["kind"] == k and e["docs"])}
                               for k in raw["asset_kinds"] if k in asset_counts},
                    "webhook_steps": len(webhooks), "denied": denied},
        "summary": counts,
        "findings": inv.findings,
        "integrations": integrations,
        "api_triggers": trigger_rows,
        "variables": variable_rows,
        "webhooks": sorted(webhooks, key=lambda w: (w["asset"] or "", w["asset_id"], str(w["step_id"]))),
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
