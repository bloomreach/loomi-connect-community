#!/usr/bin/env python3
"""Plan fixes to Bloomreach Engagement catalog items before writing them, and check the writes afterwards.

Usage:
  python3 catalog_fix_plan.py plan --project-id ID --project-name NAME --catalog-id ID --catalog detail.json
         [--catalog configuration.json] --items item.json [--items item.json ...]
         [--findings parity.json] [--changes changes.json] [--checks price_mismatch,...]
         [--delete ID,ID] [--engagement-key PROPERTY] [--field NAME=EFIELD] --out plan.json
  python3 catalog_fix_plan.py verify --plan plan.json --readback N=item.json [--readback N=file ...] [--out result.json]

plan: --catalog is the saved search_catalogs detail (catalog_id=...) and, for a v2 catalog, the saved
get_catalog_configuration result: the fields the catalog defines and its version. --items are saved
get_catalog_item results (a "not found" error saved as JSON counts as missing) or search_catalog_items results
with field="item_id". --findings is catalog-parity-check's JSON output (catalog_parity.py --out); --changes is a
list of changes the user asked for (references/change-format.md). --delete names items the user explicitly asked
to delete. Prints a summary and writes the plan, in the shape in docs/skill-authoring.md ("Plan files for write
skills") with project_id and project_name, to --out.

upsert_catalog_item replaces the whole item: every update sends the item's full current properties with only the
fixed fields changed, and its undo sends the full item as it was read. Margin, cost and similar fields are never
changed, and a field the catalog doesn't define is never added (that would change the catalog's schema).

verify: --readback N=FILE is a get_catalog_item result read after writing change N. Reports each change as
in_place, not_in_place or gone, and lists any property the write wiped. Any error other than "Item ... not found"
stops it: an error about the project, access or a rate limit says nothing about the item.

It never calls Loomi Connect: the assistant makes each write, after confirmation. Standard library only.
"""
import argparse
import copy
import json
import math
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
MISSING = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}
NOT_FOUND_RE = re.compile(r"^\s*Item '(.*)' not found in catalog '[^']*'\s*$", re.S)
PROTECTED = re.compile(RULES["protected_field_pattern"], re.I)
FIX_FIELD = {"price_mismatch": "price", "sale_price_mismatch": "sale_price", "url_mismatch": "url",
             "image_mismatch": "image", "title_mismatch": "title",
             "stock_out_on_site_in_engagement": "availability", "stock_in_on_site_out_in_engagement": "availability"}
STOCK_TARGET = {"stock_out_on_site_in_engagement": "out", "stock_in_on_site_out_in_engagement": "in"}
NOT_FIXED = {
    "missing_in_engagement": "Creating an item needs its full record from the product feed; this skill only updates "
                             "and deletes. Fix the Engagement import so it includes the product.",
    "missing_in_discovery": "Not deleted: this skill deletes an item only when you ask for that item by ID. Consider "
                            "fixing the import, or a recommendation filter, instead.",
}
NUMERIC_TYPES = {"number", "integer", "float", "long", "double", "decimal"}
SYSTEM_KEYS = {"_id", "catalog_id", "item_id"}
UNDO_NOTE_DELETE = ("The undo recreates the item with upsert_catalog_item from the full record saved here. "
                    "Recommendations and emails can't show it until it's back.")


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


def redact(text):
    """Tool error text without URLs (they can carry account numbers or keys), cut to a sensible length."""
    return re.sub(r"(?i)\b(?:https?|wss?)://\S+", "<url>", str(text or "no error text"))[:300]


def number(v):
    """A Decimal from a tool value ("$1,000.00", "2.50%", "(12.00)"), or None when missing or not a number.

    The repo's number helper (discovery-zero-results-triage), returning Decimal so money stays exact."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(v)) if math.isfinite(v) else None
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
    try:
        x = Decimal(m.group(0))
    except InvalidOperation:
        return None
    if not x.is_finite():
        return None
    return -x if negative else x


def plain_number(d):
    """A Decimal as a JSON number: an int when it's whole, else a float of its exact decimal text."""
    if d == d.to_integral_value():
        return int(d)
    return float(format(d.normalize(), "f"))


def plain_text(d):
    return format(d.normalize(), "f") if d != d.to_integral_value() else str(int(d))


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")


def norm_id(v):
    s = str(v).strip()
    return s.lower() if RULES["id_case_insensitive"] else s


def unwrap(data):
    """(data, error): strips {"result": ...} layers and returns a success:false error as text."""
    while isinstance(data, dict) and isinstance(data.get("result"), (dict, list)) and "success" not in data:
        data = data["result"]
    if isinstance(data, dict) and (data.get("success") is False or data.get("isError") is True
                                   or (data.get("error") and data.get("success") is not True)):
        return None, str(data.get("error") or "no error text")
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], (dict, list)):
        data = data["data"]
    return data, None


def item_records(data):
    """[(item_id, properties)] from a get_catalog_item or search_catalog_items result."""
    recs = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    out = []
    for r in recs:
        if not isinstance(r, dict) or r.get("_id") in (None, ""):
            continue
        props = r.get("properties")
        if not isinstance(props, dict):  # a flat record, as get_catalog_item's description says
            props = {k: v for k, v in r.items() if k not in SYSTEM_KEYS}
        out.append((str(r["_id"]), r.get("catalog_id"), props))
    return out


def load_items(paths, catalog_id, key):
    """Items by normalised key, and the keys reported not found."""
    items, not_found = {}, set()
    for p in paths:
        data, err = unwrap(read_json(p))
        if err is not None:
            m = NOT_FOUND_RE.match(err)
            if m:
                not_found.add(norm_id(m.group(1)))
                continue
            fail(f"{p}: Loomi Connect returned an error: {redact(err)} This read didn't reach the item: check the "
                 "project, catalog and access, and read it again. Don't treat it as 'not found'.")
        for rid, cid, props in item_records(data):
            if cid not in (None, "") and str(cid) != catalog_id:
                fail(f"{p}: item {rid} is from catalog {cid}, not {catalog_id}. Read the items from the catalog "
                     "you are fixing.")
            k = props.get(key) if key else rid
            if k in (None, ""):
                continue
            items[norm_id(k)] = {"item_id": rid, "properties": props}
    return items, not_found


def load_catalog(paths, catalog_id):
    """(name, version, {field: type or None}) from search_catalogs detail and get_catalog_configuration."""
    name, version, fields = None, None, {}
    for p in paths:
        data, err = unwrap(read_json(p))
        if err is not None:
            fail(f"{p}: Loomi Connect returned an error: {redact(err)} The catalog's fields couldn't be read.")
        if not isinstance(data, dict):
            fail(f"{p}: expected a search_catalogs detail or a get_catalog_configuration result.")
        cid = data.get("_id") or data.get("catalog_id")
        if cid not in (None, "") and str(cid) != catalog_id:
            fail(f"{p}: this is catalog {cid}, not {catalog_id}.")
        name = data.get("name") or name
        version = data.get("catalog_version") or version
        for f in data.get("fields") or []:
            if isinstance(f, dict) and f.get("name"):
                fields[f["name"]] = str(f.get("type") or "").lower() or None
        for group in ("custom_attribute_definitions", "reserved_attribute_mappings"):
            for f in data.get(group) or []:
                if not isinstance(f, dict):
                    continue
                t = str((f.get("attribute_value_definition") or {}).get("type") or "").lower() or None
                for n in (f.get("record_field_name"), f.get("name")):
                    if n:
                        fields.setdefault(n, t)
        if "custom_attribute_definitions" in data or "configuration_hash" in data:
            version = version or "v2"
    return name, version, fields


# ---------------------------------------------------------------------------------------------
# Requests: what the user or the parity findings ask to change

class Request:
    def __init__(self, key, source, reason, shown_id=None):
        self.key, self.source, self.reason, self.shown_id = key, source, reason, shown_id
        self.sets = []      # (field or None, logical name, kind, value, parity's Engagement value, source)
        self.delete = False
        self.problems, self.warnings = [], []


def ids(values):
    return [x.strip() for s in values for x in str(s).split(",") if x.strip()]


def requests_from_findings(path, checks_filter, deletes, overrides):
    data = read_json(path)
    if not isinstance(data, dict) or data.get("ok") is not True or not isinstance(data.get("findings"), list):
        fail(f"{path}: not catalog-parity-check output (expected ok: true and a findings list from catalog_parity.py).")
    if not str(data.get("id_mapping") or "").rstrip().split(",")[0].endswith("item ID") and not overrides.get("_key"):
        fail(f"{path}: the parity check matched products on '{data.get('id_mapping')}', not the Engagement item ID. "
             "Pass --engagement-key with the Engagement property it used, and read items by that property.")
    reqs, not_planned, notes = [], [], []
    if data.get("findings_total", 0) > len(data["findings"]):
        notes.append(f"The parity output lists {len(data['findings'])} of {data['findings_total']} products with "
                     "findings. Run catalog_parity.py again with a larger --top to plan the rest.")
    for f in data["findings"]:
        if not isinstance(f, dict) or f.get("product_id") in (None, ""):
            continue
        pid = str(f["product_id"])
        r = Request(norm_id(pid), "parity", None, pid)
        fixed = []
        for c in f.get("checks") or []:
            check = c.get("check")
            if checks_filter and check not in checks_filter:
                continue
            if check in NOT_FIXED:
                if check == "missing_in_discovery" and norm_id(pid) in deletes:
                    continue  # the user asked to delete it: planned from --delete
                not_planned.append({"product_id": pid, "check": check, "why": NOT_FIXED[check]})
                continue
            if check not in FIX_FIELD:
                not_planned.append({"product_id": pid, "check": check, "why": "Not a check this skill fixes."})
                continue
            name = FIX_FIELD[check]
            efield = str(c.get("fields") or "").split(" / ")[-1].strip()
            efield = None if efield in ("", "-") else efield
            if name in overrides:
                efield = overrides[name]
            if name == "availability":
                r.sets.append((efield, name, "stock", STOCK_TARGET[check], c.get("engagement"), "parity"))
                fixed.append(check)
            elif check == "sale_price_mismatch" and c.get("detail") == "sale price only in engagement":
                not_planned.append({"product_id": pid, "check": check,
                                    "why": "Discovery shows no discount here. Removing a sale price can't be done "
                                           "safely by guessing a value: give the value to set in a change file."})
            else:
                r.sets.append((efield, name, "set", c.get("discovery"), c.get("engagement"), "parity"))
                fixed.append(check)
        if r.sets:
            r.reason = "catalog-parity-check: " + ", ".join(fixed)
            reqs.append(r)
    return reqs, not_planned, notes


def requests_from_changes(path):
    data = read_json(path)
    if isinstance(data, dict) and isinstance(data.get("changes"), list):
        data = data["changes"]
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        fail(f"{path}: expected a JSON list of change objects (references/change-format.md).")
    reqs = []
    for i, raw in enumerate(data, 1):
        item = raw.get("item_id")
        r = Request(norm_id(item) if item not in (None, "") else None, "request", raw.get("reason"),
                    str(item) if item not in (None, "") else None)
        action = raw.get("action")
        if r.key is None:
            r.problems.append({"check": "item", "message": f"Change {i} has no item_id."})
        if action == "delete":
            r.delete = True
            if raw.get("user_asked") is not True:
                r.problems.append({"check": "delete", "message": "A delete needs \"user_asked\": true: plan it only "
                                   "when the user asked to delete this item by name or ID."})
        elif action == "update":
            sets = raw.get("set")
            if not isinstance(sets, dict) or not sets:
                r.problems.append({"check": "set", "message": f"Change {i}: an update needs a non-empty \"set\" object."})
            else:
                for field, value in sorted(sets.items()):
                    r.sets.append((str(field), str(field), "set", value, None, "request"))
        else:
            r.problems.append({"check": "action", "message": f"Change {i}: action must be update or delete."})
        reqs.append(r)
    return reqs


# ---------------------------------------------------------------------------------------------
# Working out each new value

def is_numeric_field(field, schema):
    return (schema.get(field) or "") in NUMERIC_TYPES


def strict_number(v):
    """A Decimal for a number, or a string that is only a number ("12", "12.50"); else None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(v)) if math.isfinite(v) else None
    if isinstance(v, str) and re.fullmatch(r"\s*-?(\d+\.?\d*|\.\d+)\s*", v):
        return Decimal(v.strip())
    return None


def same_value(a, b):
    """Values equal, treating 12, 12.0 and "12.00" as the same number."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    na, nb = strict_number(a), strict_number(b)
    if na is not None and nb is not None:
        return na == nb
    return a == b


def stock_state(v):
    if v is None:
        return "unknown"
    if isinstance(v, bool):
        return "in" if v else "out"
    if isinstance(v, (int, float)):
        return "in" if v > 0 else "out"
    text = str(v).strip().lower()
    for in_word, out_word in RULES["stock_text_pairs"]:
        if text == in_word:
            return "in"
        if text == out_word:
            return "out"
    n = number(text)
    if n is not None:
        return "in" if n > 0 else "out"
    return "unknown"


def stock_value(current, target, field, schema):
    """(new value, problem): the value that says `target` ("in" or "out") in the item's own vocabulary."""
    if current is None:
        return None, f"The item has no value in '{field}', so there's no vocabulary to follow. Give the value in a change file."
    if isinstance(current, bool):
        return target == "in", None
    if isinstance(current, (int, float)) or is_numeric_field(field, schema) or number(current) is not None:
        if target == "out":
            zero = RULES["stock_out_number"]
            return (str(zero) if isinstance(current, str) else zero), None
        return None, (f"'{field}' holds a stock quantity, and the right quantity isn't known. Give it in a change "
                      "file (for example the site's stock level).")
    text = str(current).strip()
    for in_word, out_word in RULES["stock_text_pairs"]:
        if text.lower() in (in_word, out_word):
            new = in_word if target == "in" else out_word
            if text.isupper():
                new = new.upper()
            elif text.istitle():
                new = new.title()
            elif text[:1].isupper():
                new = new[:1].upper() + new[1:]
            return new, None
    return None, f"'{field}' holds '{text[:40]}', which isn't a stock word in rules.json. Give the value in a change file."


def host(v):
    if not isinstance(v, str) or "://" not in v:
        return None
    return (urlsplit(v.strip()).hostname or "").lower() or None


def resolve_field(efield, name, item_props, schema):
    if efield:
        return efield
    for f in RULES["default_engagement_fields"].get(name, []):
        if f in item_props:
            return f
    for f in RULES["default_engagement_fields"].get(name, []):
        if f in schema:
            return f
    return None


def new_value(field, kind, value, current, schema, source):
    """(value to write, problem or None)."""
    if kind == "stock":
        return stock_value(current, value, field, schema)
    if value is None:
        return None, f"No value to set for '{field}'."
    numeric = is_numeric_field(field, schema) or field in RULES["default_engagement_fields"]["price"] \
        or field in RULES["default_engagement_fields"]["sale_price"]
    if numeric and not isinstance(value, bool):
        d = number(value)
        if d is None:
            return None, f"'{field}' is a number field and {str(value)[:40]!r} isn't a number."
        if (schema.get(field) or "") in ("integer", "long") and d != d.to_integral_value():
            return None, f"'{field}' holds whole numbers and {plain_text(d)} isn't one."
        declared = schema.get(field) or ""
        if (declared and declared not in NUMERIC_TYPES) or (not declared and isinstance(current, str)):
            return plain_text(d), None
        return plain_number(d), None
    if isinstance(value, str) and source == "parity" and len(value) >= RULES["truncated_value_chars"]:
        return None, (f"The Discovery value for '{field}' is {len(value)} characters, which is where the parity "
                      "output cuts values off. Give the full value in a change file.")
    return value, None


# ---------------------------------------------------------------------------------------------

def visible(props):
    """Properties to show a person: protected fields left out."""
    return {k: v for k, v in sorted(props.items()) if not PROTECTED.search(k)}


def delete_shown(before):
    """A deleted item for the chat: its field names, plus title, URL and price only."""
    if not isinstance(before, dict):
        return before
    out = {"fields": sorted(k for k in before if not PROTECTED.search(k))}
    for name in ("title", "url", "price"):
        for f in RULES["default_engagement_fields"][name]:
            if before.get(f) not in (None, "") and not PROTECTED.search(f):
                out[f] = before[f]
                break
    return out


def hidden(props):
    return sorted(k for k in props if PROTECTED.search(k))


def change(n, status, kind, target, tool, payload, before, after, undo, problems, warnings, **extra):
    live = "live" if status == "ready" else "none"
    note = None
    if status == "ready":
        note = ("Recommendations, emails and weblayers that read this catalog use the new values once the index "
                "updates." if kind == "update" else "Permanent: recommendations, emails and weblayers stop showing "
                "this item once the index updates.")
    return dict({"n": n, "status": status, "kind": kind, "target": target, "tool": tool, "payload": payload,
                 "before": before, "after": after, "undo": undo, "live_impact": live, "impact_note": note,
                 "problems": problems, "warnings": warnings}, **extra)


def plan_update(r, item, a, schema):
    props = item["properties"]
    new_props = copy.deepcopy(props)
    problems, warnings = list(r.problems), list(r.warnings)
    wanted, skipped = {}, []

    def problem(src, check, message, name):
        # A parity fix that can't be made is skipped, and the item's other fixes go ahead. A fix the user asked
        # for blocks the whole change, so nothing they asked for is silently dropped.
        if src == "parity":
            skipped.append({"fix": name, "check": check, "message": message})
        else:
            problems.append({"check": check, "message": message})

    for efield, name, kind, value, parity_ev, src in r.sets:
        field = resolve_field(efield, name, props, schema)
        if field is None:
            problem(src, "field", f"No Engagement field for {name}: the item has none of "
                    f"{', '.join(RULES['default_engagement_fields'].get(name, [])) or name} and the catalog defines "
                    "none. Adding a field changes the catalog's schema, which this skill never does.", name)
            continue
        if PROTECTED.search(field):
            problem(src, "protected", f"'{field}' is a margin or cost field: never changed.", name)
            continue
        if schema and field not in schema:
            problem(src, "schema", f"The catalog doesn't define '{field}'. Writing it would add a field to the "
                    "catalog's schema, which this skill never does.", name)
            continue
        if not schema and field not in props:
            problem(src, "schema", f"The item has no '{field}' and the catalog's field list wasn't read, so adding "
                    "it could change the schema. Pass the catalog detail with --catalog.", name)
            continue
        val, why = new_value(field, kind, value, props.get(field), schema, src)
        if why:
            problem(src, "value", why, name)
            continue
        if field in wanted and not same_value(wanted[field], val):
            problems.append({"check": "conflict", "message": f"Two fixes set '{field}' to different values "
                             f"({wanted[field]!r} and {val!r}). Choose one in a change file."})
            continue
        if name in ("url", "image") and kind == "set":
            if not str(val).strip().lower().startswith("https://"):
                problem(src, "url", f"The new {name} for '{field}' isn't an https:// address.", name)
                continue
            old_host, new_host = host(props.get(field)), host(val)
            if old_host and new_host != old_host:
                warnings.append({"check": "host", "message": f"The new {name} is on {new_host}, not {old_host} "
                                 "like the item's current one: check it's the right site."})
        wanted[field] = val
        if parity_ev is not None and kind == "set" and props.get(field) is not None \
                and not same_value(parity_ev, props.get(field)):
            warnings.append({"check": "changed since parity", "message": f"'{field}' is {props.get(field)!r} now, "
                             f"not {parity_ev!r} as in the parity check: the catalog changed since."})
    if not wanted and skipped and not problems:  # nothing left to fix on this item
        problems = [{"check": x["check"], "message": x["message"]} for x in skipped]
        skipped = []
    changed = {f: v for f, v in sorted(wanted.items()) if not (f in props and same_value(props[f], v))}
    if schema:
        held = sum(1 for f in schema if f in props)
        if held < len(schema) * RULES["sparse_item_min_share"]:
            warnings.append({"check": "sparse item", "message": f"The item holds {held} of the {len(schema)} fields "
                             "the catalog defines: an earlier partial write may have wiped it. The update keeps "
                             "exactly what it holds now; the full record has to come from the feed."})
    for f in changed:
        new_props[f] = changed[f]
    target = f"item {item['item_id']}"
    payload = {"project_id": a.project_id, "catalog_id": a.catalog_id, "item_id": item["item_id"],
               "properties": new_props}
    undo = [{"tool": "upsert_catalog_item", "payload": {"project_id": a.project_id, "catalog_id": a.catalog_id,
                                                        "item_id": item["item_id"], "properties": props},
             "note": "Writes the full item back as it was read before the change."}]
    extra = {"reason": r.reason, "source": r.source, "item_id": item["item_id"]}
    if skipped:
        extra["skipped"] = skipped
    if hidden(props):
        extra["protected_fields_kept"] = hidden(props)
    if problems:
        return change(None, "blocked", "update", target, "upsert_catalog_item", None, None, None, [], problems,
                      warnings, **extra)
    if not changed:
        return change(None, "no_change", "update", target, "upsert_catalog_item", None, None, None, [], [],
                      warnings, **extra)
    return change(None, "ready", "update", target, "upsert_catalog_item", payload,
                  {f: props.get(f) for f in changed}, changed, undo, [], warnings, **extra)


def plan_delete(r, item, a):
    props = item["properties"]
    warnings = [{"check": "permanent", "message": "delete_catalog_item is permanent. " + UNDO_NOTE_DELETE}]
    extra = {"reason": r.reason, "source": r.source, "item_id": item["item_id"]}
    if hidden(props):
        extra["protected_fields_hidden"] = hidden(props)
    if r.problems:
        return change(None, "blocked", "delete", f"item {item['item_id']}", "delete_catalog_item", None, None, None,
                      [], list(r.problems), warnings, **extra)
    payload = {"project_id": a.project_id, "catalog_id": a.catalog_id, "item_id": item["item_id"]}
    undo = [{"tool": "upsert_catalog_item", "payload": {"project_id": a.project_id, "catalog_id": a.catalog_id,
                                                        "item_id": item["item_id"], "properties": props},
             "note": UNDO_NOTE_DELETE}]
    return change(None, "ready", "delete", f"item {item['item_id']}", "delete_catalog_item", payload, visible(props),
                  None, undo, [], warnings, **extra)


def import_safe(item_id):
    return "/" not in item_id and "~" not in item_id


def build_batches(changes, cap, probe_import):
    """Updates in batches of at most cap, then each delete alone. With probe_import, the first batch is one item,
    written with import_catalog_items and verified before the rest, because the import's shape isn't yet confirmed."""
    ready = [ch for ch in changes if ch["status"] == "ready"]
    updates = [ch["n"] for ch in ready if ch["kind"] != "delete" and import_safe(ch.get("item_id") or "")]
    updates += [ch["n"] for ch in ready if ch["kind"] != "delete" and ch["n"] not in updates]
    deletes = [[ch["n"]] for ch in ready if ch["kind"] == "delete"]
    head = []
    if probe_import and updates and import_safe(by_item(ready, updates[0])):
        head, updates = [[updates[0]]], updates[1:]
    return head + [updates[i:i + cap] for i in range(0, len(updates), cap)] + deletes


def by_item(ready, n):
    return next((ch.get("item_id") or "") for ch in ready if ch["n"] == n)


def build_calls(batches, by_n, a, version, probe):
    out = []
    for i, batch in enumerate(batches):
        chs = [by_n[n] for n in batch]
        if (probe and ((i == 0 and len(chs) == 1) or len(chs) >= RULES["import_min_items"]) and all(ch["kind"] == "update" for ch in chs)
                and all(import_safe(ch["item_id"]) for ch in chs)):
            ops = [{"op": "upsert", "path": "/" + ch["item_id"], "value": {"fields": ch["payload"]["properties"]}}
                   for ch in chs]
            calls = [{"tool": "import_catalog_items",
                      "payload": {"project_id": a.project_id, "catalog_id": a.catalog_id, "operations": ops},
                      "covers": batch,
                      "note": "One import for the batch. Each operation carries the item's full record, because an "
                              "upsert replaces the whole item."}]
        else:
            calls = [{"tool": ch["tool"], "payload": ch["payload"], "covers": [ch["n"]]} for ch in chs]
        out.append({"batch": batch, "calls": calls})
    return out


def cmd_plan(a):
    overrides = {}
    for name, efield in a.field:
        overrides[name] = efield
    if a.engagement_key:
        overrides["_key"] = a.engagement_key
    if not a.findings and not a.changes and not a.delete:
        fail("Nothing to plan: pass --findings, --changes or --delete.")
    checks_filter = set(ids(a.checks)) if a.checks else set()
    unknown = sorted(checks_filter - set(FIX_FIELD) - set(NOT_FIXED))
    if unknown:
        fail(f"--checks: unknown check {', '.join(unknown)}. Use the names in catalog-parity-check's output.")
    name, version, schema = load_catalog(a.catalog, a.catalog_id)
    items, not_found = load_items(a.items, a.catalog_id, a.engagement_key)
    deletes = {norm_id(x) for x in ids(a.delete)}

    reqs, not_planned, notes = [], [], []
    asked = requests_from_changes(a.changes) if a.changes else []
    asked_deletes = deletes | {r.key for r in asked if r.delete and r.key is not None}
    if a.findings:
        r2, np2, n2 = requests_from_findings(a.findings, checks_filter, asked_deletes, overrides)
        reqs += r2
        not_planned += np2
        notes += n2
    reqs += asked
    for d in sorted(deletes):
        r = Request(d, "request", "The user asked to delete this item.", d)
        r.delete = True
        reqs.append(r)

    # One change per item: updates to the same item merge; a delete and an update to one item conflict.
    merged, order = {}, []
    for r in reqs:
        k = r.key if r.key is not None else f"<no id {len(order)}>"
        if k not in merged:
            merged[k] = r
            order.append(k)
            continue
        m = merged[k]
        if m.delete != r.delete:
            m.problems.append({"check": "conflict", "message": "This item has both a delete and an update planned. "
                               "Plan one or the other."})
        m.sets += r.sets
        m.problems += r.problems
        m.reason = "; ".join(x for x in (m.reason, r.reason) if x) or None
        m.source = m.source if m.source == r.source else "parity and request"

    changes, deferred, ready = [], [], 0
    cap_plan = RULES["max_changes_per_plan"]
    for k in order:
        r = merged[k]
        item = items.get(k)
        if item is None:
            target = f"item {r.shown_id or k}"
            if k in not_found:
                if r.delete:
                    ch = change(None, "no_change", "delete", target, "delete_catalog_item", None, None, None, [], [],
                                [{"check": "gone", "message": "The item isn't in the catalog: nothing to delete."}])
                else:
                    ch = change(None, "blocked", "update", target, "upsert_catalog_item", None, None, None, [],
                                r.problems + [{"check": "not found", "message": "The item isn't in the catalog. "
                                               "upsert_catalog_item would create it with only these fields; this "
                                               "skill never creates items."}], [])
            else:
                ch = change(None, "blocked", "delete" if r.delete else "update", target,
                            "delete_catalog_item" if r.delete else "upsert_catalog_item", None, None, None, [],
                            r.problems + [{"check": "not read", "message": "Read the item with get_catalog_item "
                                           "first: without its current record the change can't be planned or undone."}],
                            [])
        else:
            ch = plan_delete(r, item, a) if r.delete else plan_update(r, item, a, schema)
        if ch["status"] == "ready":
            if ready >= cap_plan:
                deferred.append({"item_id": ch.get("item_id"), "kind": ch["kind"], "reason": ch.get("reason")})
                continue
            ready += 1
        changes.append(ch)
    for n, ch in enumerate(changes, 1):
        ch["n"] = n
    by_n = {ch["n"]: ch for ch in changes}
    ready_updates = sum(1 for ch in changes if ch["status"] == "ready" and ch["kind"] == "update")
    probe = bool(a.use_import and version == "v2" and ready_updates >= RULES["import_min_items"])
    batches = build_batches(changes, RULES["max_changes_per_batch"], probe)
    if not schema:
        notes.append("The catalog's field list wasn't read (pass the search_catalogs detail, and for a v2 catalog "
                     "get_catalog_configuration, with --catalog): fields the item doesn't already hold are blocked.")
    notes.append("The product feed or catalog import overwrites these fixes the next time it runs, unless the feed "
                 "is fixed too.")
    plan = {"ok": True, "project_id": a.project_id, "project_name": a.project_name, "catalog_id": a.catalog_id,
            "catalog_name": name, "catalog_version": version,
            "write_semantics": "upsert_catalog_item replaces the whole item (fields left out are removed), so each "
                               "payload holds the full record with only the fixed fields changed.",
            "changes": changes, "batches": batches, "batch_calls": build_calls(batches, by_n, a, version, probe),
            "batch_cap": RULES["max_changes_per_batch"], "deferred": deferred,
            "not_planned": sorted(not_planned, key=lambda x: (x["check"], str(x["product_id"]).lower())),
            "notes": notes,
            "counts": {s: sum(1 for ch in changes if ch["status"] == s) for s in ("ready", "blocked", "no_change")}}
    write_out(a.out, json.dumps(plan, indent=2, ensure_ascii=False))
    summary = {k: plan[k] for k in ("ok", "project_name", "catalog_name", "catalog_version", "counts", "batches",
                                    "deferred", "not_planned", "notes")}
    summary["out"] = a.out
    summary["calls_per_batch"] = [{"batch": b["batch"], "tools": [c["tool"] for c in b["calls"]]}
                                  for b in plan["batch_calls"]]
    summary["changes"] = [{k: (delete_shown(ch["before"]) if k == "before" and ch["kind"] == "delete" else ch.get(k))
                           for k in ("n", "status", "kind", "target", "before", "after", "reason", "skipped",
                                     "problems", "warnings") if k != "skipped" or ch.get(k)}
                          for ch in changes]
    return summary


# ---------------------------------------------------------------------------------------------

def readback(path, item_id):
    """(properties or None when not found)."""
    data, err = unwrap(read_json(path))
    if err is not None:
        m = NOT_FOUND_RE.match(err)
        if m and m.group(1) == item_id:
            return None
        fail(f"{path}: {redact(err)} The read-back didn't reach the item (check the project, catalog and access, "
             "or wait on a rate limit), so nothing was checked. Read it again.")
    for rid, _cid, props in item_records(data):
        if rid == item_id:
            return props
    # Only "Item '<this id>' not found" means the item is gone. An empty list, another item or an unexpected shape
    # says nothing about it, and reading it as gone could lead to an undo that overwrites a change that landed.
    fail(f"{path}: the read-back doesn't hold item {item_id} and isn't a not-found error for it, so nothing was "
         "checked. Read the item again with get_catalog_item.")


def shown(field, value):
    return "(hidden)" if PROTECTED.search(field) else value


def cmd_verify(a):
    plan = read_json(a.plan)
    if not isinstance(plan, dict) or not isinstance(plan.get("changes"), list):
        fail(f"{a.plan}: not a plan file (no changes list). Use the file that catalog_fix_plan.py plan wrote.")
    by_n = {ch.get("n"): ch for ch in plan["changes"] if isinstance(ch, dict) and isinstance(ch.get("n"), int)}
    files = dict(a.readback)
    results = []
    for n in sorted(files):
        ch = by_n.get(n)
        if ch is None or ch.get("status") != "ready" or not isinstance(ch.get("payload"), dict):
            fail(f"--readback {n}: the plan has no ready change {n}.")
        item_id = ch["payload"]["item_id"]
        props = readback(files[n], item_id)
        res = {"n": n, "kind": ch["kind"], "target": ch["target"]}
        if ch["kind"] == "delete":
            res["state"] = "gone" if props is None else "not_in_place"
            if props is not None:
                res["note"] = "The item is still in the catalog. v1 deletes are queued: read it again shortly."
        elif props is None:
            res["state"] = "gone"
            res["alert"] = "The item is no longer in the catalog. Tell the user; the undo in the plan restores it."
        else:
            planned = ch["payload"]["properties"]
            after = ch.get("after") or {}
            bad = [{"field": f, "planned": shown(f, v), "found": shown(f, props.get(f))}
                   for f, v in sorted(after.items()) if not same_value(v, props.get(f))]
            wiped = sorted(f for f in planned if f not in after and f not in props)
            altered = sorted(f for f in planned if f not in after and f in props and not same_value(planned[f], props[f]))
            res["state"] = "in_place" if not (bad or wiped or altered) else "not_in_place"
            if bad:
                res["mismatches"] = bad
                before = ch.get("before") or {}
                if all(same_value(before.get(m["field"]), props.get(m["field"])) for m in bad):
                    res["note"] = ("Still the old values: the write may not be indexed yet (v1 writes are queued, v2 "
                                   "writes finish when their list_catalog_jobs job succeeds). Read it again before "
                                   "treating it as failed.")
            if wiped:
                res["wiped"] = wiped
                res["alert"] = "Properties the plan kept are missing after the write. Stop and offer the undo."
            if altered:
                res["other_fields_changed"] = altered
        results.append(res)
    unchecked = sorted(n for n, ch in by_n.items() if ch.get("status") == "ready" and n not in files)
    return {"ok": True, "results": results, "not_checked": unchecked}


def numbered_file(text):
    """N=FILE, split on the first "=": a plan change number and its read-back file."""
    n, sep, path = text.partition("=")
    if not sep or not path:
        raise argparse.ArgumentTypeError("use N=FILE, e.g. 3=readback-3.json")
    try:
        return int(n), path
    except ValueError:
        raise argparse.ArgumentTypeError(f"{n!r} isn't a change number")


def field_override(text):
    name, sep, efield = text.partition("=")
    names = sorted(RULES["default_engagement_fields"])
    if not sep or name.strip() not in names or not efield.strip():
        raise argparse.ArgumentTypeError(f"expected NAME=EFIELD with NAME one of {', '.join(names)}, got {text!r}")
    if PROTECTED.search(efield):
        raise argparse.ArgumentTypeError(f"{text!r}: margin, cost and similar fields are never changed")
    return name.strip(), efield.strip()


def write_out(path, text):
    if path:
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"{path}: can't write it ({e}).")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # product text can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="turn the requested fixes into a plan")
    p.add_argument("--project-id", required=True, help="the Engagement project ID the user confirmed")
    p.add_argument("--project-name", required=True, help="the project's name, shown in the plan")
    p.add_argument("--catalog-id", required=True, help="the catalog ID from search_catalogs")
    p.add_argument("--catalog", action="append", required=True,
                   help="saved search_catalogs detail, and for a v2 catalog get_catalog_configuration (repeat)")
    p.add_argument("--items", action="append", default=[],
                   help="saved get_catalog_item or search_catalog_items result for an item to change (repeat)")
    p.add_argument("--findings", help="catalog-parity-check's JSON output (catalog_parity.py --out)")
    p.add_argument("--changes", help="JSON list of changes the user asked for (references/change-format.md)")
    p.add_argument("--checks", action="append", default=[],
                   help="comma-separated parity checks to fix, e.g. price_mismatch (default: every one it can)")
    p.add_argument("--delete", action="append", default=[],
                   help="comma-separated item IDs the user explicitly asked to delete (repeatable)")
    p.add_argument("--engagement-key", help="the Engagement property the parity check matched on, if not the item ID")
    p.add_argument("--field", action="append", default=[], type=field_override,
                   help="NAME=EFIELD: write parity check NAME (price, sale_price, availability, url, image, title) to this Engagement field")
    p.add_argument("--use-import", action="store_true", default=RULES["use_import_for_v2"],
                   help="write large v2 batches with one import_catalog_items call (default: use_import_for_v2 in rules.json)")
    p.add_argument("--out", required=True, help="write the full plan (payloads and undo) to this file")
    v = sub.add_parser("verify", help="check the read-backs after writing")
    v.add_argument("--plan", required=True, help="the plan file from the plan step")
    v.add_argument("--readback", action="append", type=numbered_file, required=True,
                   help="N=FILE: the get_catalog_item result read after writing change N (repeat)")
    v.add_argument("--out", help="also write the result to this file")
    a = ap.parse_args()
    out = cmd_plan(a) if a.cmd == "plan" else cmd_verify(a)
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.cmd == "verify":
        write_out(a.out, text)
    print(text)


if __name__ == "__main__":
    main()
