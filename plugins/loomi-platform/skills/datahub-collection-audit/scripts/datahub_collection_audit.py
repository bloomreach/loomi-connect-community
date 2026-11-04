#!/usr/bin/env python3
"""Audit the item collections of one Bloomreach Data Hub workspace from saved Loomi Connect results.

Usage:
  python3 datahub_collection_audit.py --collections collections.json
         [--config NAME[:TYPE]=config.json ...] [--fields NAME[:TYPE]=fields.json ...]
         [--records NAME[:TYPE]=records-page.json ...] [--system NAME[:TYPE]=system.json ...]
         [--jobs jobs.json ...] [--catalogs datahub-catalogs.json]
         [--pair A,B ...] [--compare A,B=compare.json ...] [--no-auto-pair]
         [--today 2026-11-04] [--out audit.json]

NAME is the collection name and TYPE the item type (default: product). Each input is a saved tool result:
--collections search_item_collections (list), --config get_item_collection_configuration, --fields
search_item_collection_fields (summary mode), --records search_item_collection_records list pages (repeat per page),
--system get_datahub_system_configuration, --jobs search_datahub_jobs, --catalogs search_datahub_catalogs,
--compare compare_item_collection_configurations (base A, reference B).

Prints JSON: findings sorted by priority (high, medium, low), each with the collection, item type, subject, what's
wrong, the fix, who owns it and a hand-off skill; a table per collection; the pairs compared; and what couldn't be
checked. Record values are never printed, only field names, fill rates and type-mismatch counts.

Thresholds, word lists and owners are in references/rules.json. Standard library only; no network access.
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# The thresholds live in references/rules.json, next to this script's folder.
RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
PRIORITIES = ("high", "medium", "low")
URL = re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s\"'<>]+", re.I)
CONTEXT_WORDS = ("workspace", "organisation", "organization", "project", "account", "access", "permission",
                 "unauthori", "forbidden", "401", "403", "429", "rate limit", "too many requests", "data hub url")
DEFAULT_TYPE = "product"


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def redact(text):
    """Error text safe to repeat: URLs removed, length capped."""
    return URL.sub("<url>", str(text or "no error text")).strip()[:200]


def is_context_error(text):
    low = str(text or "").lower()
    return any(w in low for w in CONTEXT_WORDS)


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")


def unwrap(path, data):
    """The payload of a saved result, or (None, error) when the tool returned success: false. Errors about the
    workspace, project, organisation or access, and 401/403/429, stop the run."""
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            err = d.get("error")
            if is_context_error(err):
                fail(f"{path}: Loomi Connect returned an error about the workspace or access: {redact(err)} "
                     "Stop and check the workspace (Data Hub must be enabled: data_engine_url set) and the user's access.")
            return None, redact(err)
    if isinstance(data, dict) and isinstance(data.get("result"), (dict, list)):
        data = data["result"]
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], (dict, list)):
        data = data["data"]
    return data, None


def as_list(data):
    if isinstance(data, dict):
        return [data]
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def today_arg(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {text!r}")


def keyed(text, what):
    """NAME[:TYPE]=FILE, split on the first '='."""
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"{what} must look like NAME[:TYPE]=FILE, got {text!r}")
    left, path = text.split("=", 1)
    name, _, itype = left.partition(":")
    if not name.strip() or not path.strip():
        raise argparse.ArgumentTypeError(f"{what} must look like NAME[:TYPE]=FILE, got {text!r}")
    return (name.strip(), itype.strip() or DEFAULT_TYPE), path


def pair_arg(text):
    a, sep, b = text.partition(",")
    if not sep or not a.strip() or not b.strip():
        raise argparse.ArgumentTypeError(f"--pair must look like A,B, got {text!r}")
    return a.strip(), b.strip()


def compare_arg(text):
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"--compare must look like A,B=FILE, got {text!r}")
    left, path = text.split("=", 1)
    return pair_arg(left), path


def short(names):
    names = sorted(set(names))
    n = RULES["list_limit"]
    return ", ".join(names[:n]) + (f" and {len(names) - n} more" if len(names) > n else "")


def filled(v):
    return v not in (None, "", [], {}) and not (isinstance(v, str) and not v.strip())


def when(v):
    """A datetime (UTC) from an ISO string or Unix seconds/milliseconds, or None."""
    if isinstance(v, bool) or v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        secs = v / 1000 if v > 1e11 else v
        try:
            return datetime.fromtimestamp(secs, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def kind_of(value):
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return None


INFERRED = {"string": "string", "str": "string", "text": "string", "float": "number", "double": "number",
            "number": "number", "decimal": "number", "int": "integer", "integer": "integer", "long": "integer",
            "bool": "boolean", "boolean": "boolean", "list": "list", "array": "list", "object": "object",
            "dict": "object", "map": "object"}


def expected_kind(data_type):
    if not isinstance(data_type, str) or not data_type.strip():
        return None
    dt = data_type.strip()
    if dt.lower().startswith("list"):
        return "list"
    lookup = {k.lower(): v for k, v in RULES["type_map"].items()}
    return lookup.get(dt.lower())


def fits(expected, actual):
    if actual is None or expected is None:
        return True
    if expected == "number":
        return actual in ("number", "integer")
    return expected == actual


class Report:
    def __init__(self):
        self.findings, self.not_checked = [], []

    def add(self, priority, check, collection, item_type, subject, issue, fix, owner, hand_off=None):
        self.findings.append({"priority": priority, "check": check, "collection": collection, "item_type": item_type,
                              "subject": subject, "issue": issue, "fix": fix, "owner": RULES["owners"][owner],
                              "hand_off": hand_off})


# ----------------------------------------------------------------------------------------------
# Collections and item types

def collection_types(c):
    """[(type name, item_class, destinations or None)] from a collection record (types or item_types)."""
    out = {}
    for t in c.get("types") or []:
        if isinstance(t, dict) and t.get("name"):
            out[t["name"]] = (t.get("item_class"), t.get("destinations"))
    for t in c.get("item_types") or []:
        if isinstance(t, dict) and t.get("type") and t["type"] not in out:
            out[t["type"]] = (None, None)
    return out


def destinations_empty(dest):
    if dest is None:
        return None
    if isinstance(dest, dict):
        return not any(v for v in dest.values())
    if isinstance(dest, list):
        return not dest
    return None


# ----------------------------------------------------------------------------------------------
# Configuration

def attr_key(a):
    return (str(a.get("name")), str(a.get("family") or ""), str(a.get("level") or ""))


def ident_fields(ident):
    names = set()
    for k in ("name", "attribute", "field", "property", "attribute_name"):
        if isinstance(ident.get(k), str) and ident[k]:
            names.add(ident[k])
    for k in ("fields", "attributes"):
        for v in ident.get(k) or []:
            if isinstance(v, str):
                names.add(v)
            elif isinstance(v, dict) and isinstance(v.get("name"), str):
                names.add(v["name"])
    return names


def parse_config(cfg):
    schema = cfg.get("schema") if isinstance(cfg.get("schema"), dict) else {}
    attrs = [a for a in schema.get("attributes") or [] if isinstance(a, dict) and a.get("name")]
    idents = [i for i in schema.get("identifiers") or [] if isinstance(i, dict)]
    required = {a["name"] for a in attrs if a.get("required") is True or a.get("is_required") is True
                or a.get("nullable") is False}
    ident_names, unreadable = set(), 0
    for i in idents:
        found = ident_fields(i)
        ident_names |= found
        unreadable += 0 if found else 1
    return {"attrs": attrs, "idents": idents, "ident_names": ident_names, "required": required,
            "unreadable_idents": unreadable, "destinations": cfg.get("destinations")}


def ident_signature(idents):
    out = {}
    for i in idents:
        key = (str(i.get("family") or ""), str(i.get("level") or ""))
        out[key] = sorted(ident_fields(i)) or sorted(f"{k}={json.dumps(v, sort_keys=True)}" for k, v in i.items()
                                                     if k not in ("family", "level"))
    return out


def dest_signature(dest):
    out = {}
    if isinstance(dest, dict):
        for platform, items in dest.items():
            names = []
            for d in items if isinstance(items, list) else [items]:
                if isinstance(d, dict):
                    names.append(str(d.get("name") or d.get("type") or d.get("id") or "?"))
            out[str(platform)] = sorted(names)
    return out


# ----------------------------------------------------------------------------------------------
# Records sample

def record_fields(rec):
    inner = None
    for k in ("fields", "attributes", "data"):
        if isinstance(rec.get(k), dict):
            inner = rec[k]
            break
    meta = set(RULES["record_meta_keys"])
    out = {k: v for k, v in rec.items() if k not in meta and k not in ("fields", "attributes", "data")}
    if inner:
        out.update(inner)
    return out


def sample_stats(records):
    n, fill, kinds = 0, {}, {}
    for rec in records:
        n += 1
        for k, v in record_fields(rec).items():
            if filled(v):
                fill[k] = fill.get(k, 0) + 1
                kd = kinds.setdefault(k, {})
                kn = kind_of(v)
                kd[kn] = kd.get(kn, 0) + 1
    return n, fill, kinds


def field_tool_stats(fields):
    """name -> {present, kinds} from search_item_collection_fields (examples carry an inferred type; values unused)."""
    out = {}
    for f in fields:
        name = f.get("name")
        if not name:
            continue
        e = out.setdefault(name, {"present": f.get("currently_present"), "kinds": {}, "level": f.get("level")})
        for ex in f.get("examples") or []:
            if not isinstance(ex, dict) or ex.get("field_value_class") == "null":
                continue
            kn = INFERRED.get(str(ex.get("field_data_type") or "").lower())
            if kn:
                e["kinds"][kn] = e["kinds"].get(kn, 0) + 1
    return out


# ----------------------------------------------------------------------------------------------
# Checks per collection and item type

def check_item_type(rep, coll, itype, cfg, n, fill, kinds, ftools, system_names, has_records, has_fields):
    attrs = cfg["attrs"] if cfg else []
    configured = {a["name"] for a in attrs}
    idents = cfg["ident_names"] if cfg else set()
    required = (cfg["required"] if cfg else set()) | idents
    parent_attrs = {a["name"]: a for a in attrs if str(a.get("level") or "parent").lower() in ("parent", "item", "product")}

    if has_records and n == 0:
        rep.add("medium", "no records", coll, itype, itype, "The records sample is empty: this item type holds no data.",
                "Check that the feed sends this item type, or remove the type if it's no longer used.", "feed",
                "data-feed-health")
    if has_records and n:
        for name in sorted(required):
            if name not in parent_attrs and name not in idents:
                continue
            share = fill.get(name, 0) / n
            if share < RULES["required_min_fill"]:
                rep.add("high", "required field missing", coll, itype, name,
                        f"{'Identifier' if name in idents else 'Required field'} {name} is filled on {share:.0%} of "
                        f"{n} sampled records.", "Fix the feed so every record sends it.", "feed", "data-feed-health")
        observed = {k for k, v in fill.items() if v} | {k for k, v in ftools.items() if v.get("present")}
        keys = set(RULES["key_fields"]) & (configured | observed)
        for name in sorted(keys - required):
            share = fill.get(name, 0) / n
            if share < RULES["key_min_fill"]:
                rep.add("medium", "key field sparse", coll, itype, name,
                        f"Key field {name} is filled on {share:.0%} of {n} sampled records.",
                        "Send it for every item.", "feed", "product-data-audit")
        never, sparse = [], []
        for name in sorted(set(parent_attrs) - required - keys):
            share = fill.get(name, 0) / n
            if share == 0:
                never.append(name)
            elif share < RULES["sparse_fill"]:
                sparse.append(name)
        if never:
            gone = [x for x in never if (ftools.get(x) or {}).get("present") is not True]
            rep.add("low", "unused field", coll, itype, short(never),
                    f"Configured but never filled in {n} sampled records"
                    + (f"; {len(gone)} of them also absent from the latest import." if has_fields and gone else "."),
                    "Remove them from the configuration if nothing sends or uses them.", "config")
        if sparse:
            rep.add("low", "sparse field", coll, itype, short(sparse),
                    f"Configured but filled on fewer than {RULES['sparse_fill']:.0%} of {n} sampled records.",
                    "Fill them in the feed, or remove them if they aren't used.", "feed")
    # Fields that stopped arriving (fields tool).
    if has_fields:
        dropped = sorted(x for x in configured | idents if (ftools.get(x) or {}).get("present") is False)
        hard = [x for x in dropped if x in required]
        if hard:
            rep.add("high", "field stopped arriving", coll, itype, short(hard),
                    "Required or identifier fields were absent from the latest import.",
                    "Find why the feed stopped sending them.", "feed", "data-feed-health")
        soft = [x for x in dropped if x not in required]
        if soft:
            rep.add("medium", "field stopped arriving", coll, itype, short(soft),
                    "Configured fields were absent from the latest import (they arrived before).",
                    "Check whether the feed dropped them on purpose; remove them from the configuration if so.",
                    "feed")
    # Fields arriving with no configuration.
    known = configured | idents | system_names | set(RULES["record_meta_keys"])
    seen = {k for k, v in fill.items() if v} | {k for k, v in ftools.items() if v.get("present")}
    extra = sorted(seen - known)
    if extra and cfg is not None:
        rep.add("low", "unconfigured field", coll, itype, short(extra),
                "These fields arrive in the data but have no attribute configuration"
                + ("" if system_names else " (pass --system to exclude built-in system fields)") + ".",
                "Configure them if Engagement or Discovery should use them; otherwise ignore.", "config")
    # Type fit.
    for a in sorted(attrs, key=attr_key):
        name = a["name"]
        exp = expected_kind(a.get("data_type"))
        if exp is None:
            continue
        counts = dict(kinds.get(name, {}))
        source = "sampled values"
        if not counts and name in ftools:
            counts, source = dict(ftools[name]["kinds"]), "import examples"
        total = sum(counts.values())
        bad = sum(c for k, c in counts.items() if not fits(exp, k))
        if total and bad / total >= RULES["type_mismatch_share"]:
            got = ", ".join(sorted(k for k in counts if not fits(exp, k)))
            rep.add("high" if name in idents else "medium", "type mismatch", coll, itype, name,
                    f"Declared {a.get('data_type')} but {bad} of {total} {source} are {got}.",
                    "Fix the values in the feed, or change the declared data type (check it with "
                    "validate_item_collection_attribute before anyone applies it).", "feed")


def unknown_types(attrs):
    return sorted({str(a.get("data_type")) for a in attrs if a.get("data_type") and expected_kind(a["data_type"]) is None})


# ----------------------------------------------------------------------------------------------
# Jobs

def job_collection(j):
    for k in ("resource_id", "target_resource_id", "collection_name"):
        if isinstance(j.get(k), str) and j[k]:
            return j[k]
    res = j.get("resource")
    if isinstance(res, dict) and isinstance(res.get("id") or res.get("name"), str):
        return res.get("name") or res.get("id")
    return None


def job_time(j):
    for k in ("finished_at", "completed_at", "ended_at", "updated_at", "updated", "created_at", "created", "started_at"):
        t = when(j.get(k))
        if t:
            return t
    return None


def check_jobs(rep, jobs, collections, today):
    succ, failed = set(RULES["success_states"]), set(RULES["failed_states"])
    data_types = set(RULES["data_job_types"])
    by = {}
    for j in jobs:
        by.setdefault(job_collection(j) or "(workspace)", []).append(j)
    latest = {}
    for coll in sorted(by):
        js = sorted(by[coll], key=lambda j: (job_time(j) or datetime.min.replace(tzinfo=timezone.utc),
                                             str(j.get("id") or j.get("_id") or "")))
        types = sorted({str(j.get("type") or j.get("job_type") or "?") for j in js})
        for jt in types:
            runs = [j for j in js if str(j.get("type") or j.get("job_type") or "?") == jt]
            states = [str(j.get("state") or j.get("status") or "").lower() for j in runs]
            last_state, last_t = states[-1], job_time(runs[-1])
            stamp = last_t.date().isoformat() if last_t else "unknown date"
            if last_state in failed:
                rep.add("high" if jt in data_types else "medium", "job failing", coll, None, jt,
                        f"The latest {jt} job ({stamp}) ended {last_state}.",
                        "Read the job's error in Data Hub, fix the cause and re-run it.", "pipeline", "data-feed-health")
            elif any(s in failed for s in states):
                rep.add("low", "job failed earlier", coll, None, jt,
                        f"{sum(s in failed for s in states)} of {len(runs)} {jt} jobs read failed; the latest succeeded.",
                        "Check whether the failures recur.", "pipeline", "data-feed-health")
        good = [job_time(j) for j in js if str(j.get("type") or j.get("job_type") or "") in data_types
                and str(j.get("state") or j.get("status") or "").lower() in succ and job_time(j)]
        latest[coll] = max(good).date().isoformat() if good else None
        if coll == "(workspace)":
            continue
        if good:
            age = (today - max(good).date()).days
            if age > RULES["stale_days"]:
                rep.add("medium", "no recent records", coll, None, "data jobs",
                        f"The latest successful data job was {age} days ago.",
                        "Check that the feed still runs on schedule.", "feed", "data-feed-health")
        elif any(str(j.get("type") or j.get("job_type") or "") in data_types for j in js):
            rep.add("medium", "no recent records", coll, None, "data jobs",
                    "None of the data jobs read succeeded.", "Check the feed and the job errors.", "pipeline",
                    "data-feed-health")
    for coll in sorted(collections):
        if coll not in by:
            rep.add("low", "no recent records", coll, None, "data jobs",
                    "No jobs for this collection in the jobs read.",
                    "Read its jobs with resource_type 'item-collection' and resource_id set to the collection name; "
                    "if there are none, nothing has written to it recently.", "feed", "data-feed-health")
    return latest


# ----------------------------------------------------------------------------------------------
# Catalogs

def catalog_link(c):
    """(collection name or ID, item type) from a catalog's item_collection_* fields; the name wins over the ID."""
    by_name = by_id = itype = None
    for k, v in sorted(c.items()):
        if not k.startswith("item_collection") or not isinstance(v, str) or not v:
            continue
        if "type" in k:
            itype = v
        elif "name" in k:
            by_name = v
        elif k.endswith("id"):
            by_id = v
    return by_name or by_id, itype


def check_catalogs(rep, catalogs, colls, coll_ids, types_by_coll):
    linked = set()
    for c in catalogs:
        ref, itype = catalog_link(c)
        if not ref:
            continue
        name = str(c.get("name") or c.get("_id") or c.get("id") or "?")
        coll = ref if ref in colls else coll_ids.get(ref)
        if coll is None:
            rep.add("medium", "catalog without collection", ref, itype, name,
                    "An Engagement catalog is linked to a Data Hub collection this workspace doesn't have.",
                    "Check whether the collection was renamed, deleted or lives in another workspace; relink or "
                    "retire the catalog.", "downstream", "data-feed-health")
            continue
        linked.add(coll)
        if itype and types_by_coll.get(coll) and itype not in types_by_coll[coll]:
            rep.add("medium", "item type without collection", coll, itype, name,
                    f"Catalog {name} expects item type {itype}, which collection {coll} doesn't have.",
                    "Recreate the item type or relink the catalog.", "downstream")
    return linked


# ----------------------------------------------------------------------------------------------
# Pairs and drift

def base_name(name):
    parts = [p for p in re.split(r"[_\-.\s]+", name.lower()) if p]
    loc = re.compile(RULES["locale_pattern"])
    keep = [p for p in parts if p not in set(RULES["pair_tokens"]) and not loc.match(p)]
    return "_".join(keep) if keep and keep != parts else None


def auto_pairs(names):
    groups = {}
    for n in sorted(names):
        b = base_name(n)
        if b:
            groups.setdefault(b, []).append(n)
    for n in sorted(names):  # the bare name ('products') belongs with 'products_staging'
        if n.lower() in groups and n not in groups[n.lower()]:
            groups[n.lower()].append(n)
    pairs = []
    for b, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        members = sorted(members)
        prod = [m for m in members if set(re.split(r"[_\-.\s]+", m.lower())) & {"prod", "production", "prd", "live"}]
        base = prod[0] if prod else (b if b in members else members[0])
        pairs += [(base, m) for m in members if m != base]
    return pairs


def drift(rep, a, b, ca, cb, itype):
    ka = {attr_key(x): x for x in ca["attrs"]}
    kb = {attr_key(x): x for x in cb["attrs"]}
    only_a = sorted(k[0] for k in set(ka) - set(kb))
    only_b = sorted(k[0] for k in set(kb) - set(ka))
    subject = f"{a} vs {b}"
    if only_a:
        rep.add("medium", "configuration drift", a, itype, subject,
                f"Attributes only in {a}: {short(only_a)}.", f"Add them to {b}, or remove them from {a}, so the pair "
                "matches.", "config")
    if only_b:
        rep.add("medium", "configuration drift", b, itype, subject,
                f"Attributes only in {b}: {short(only_b)}.", f"Add them to {a}, or remove them from {b}, so the pair "
                "matches.", "config")
    typed = sorted(k[0] for k in set(ka) & set(kb) if ka[k].get("data_type") != kb[k].get("data_type"))
    if typed:
        rep.add("medium", "configuration drift", a, itype, subject,
                f"Attributes with a different data type: {short(typed)}.", "Use one data type in both.", "config")
    other = sorted(k[0] for k in set(ka) & set(kb) if k[0] not in typed and
                   json.dumps(ka[k], sort_keys=True, default=str) != json.dumps(kb[k], sort_keys=True, default=str))
    if other:
        rep.add("low", "configuration drift", a, itype, subject,
                f"Attributes whose other settings differ: {short(other)}.", "Review and align them.", "config")
    ia, ib = ident_signature(ca["idents"]), ident_signature(cb["idents"])
    if ia != ib:
        rep.add("high", "configuration drift", a, itype, subject,
                "The identifiers differ, so the same item can get a different ID in each collection.",
                "Use the same identifier configuration in both.", "config")
    da, db = dest_signature(ca["destinations"]), dest_signature(cb["destinations"])
    if da != db:
        diff = sorted(set(da) ^ set(db)) or sorted(p for p in set(da) & set(db) if da[p] != db[p])
        rep.add("low", "configuration drift", a, itype, subject,
                f"Destinations differ ({', '.join(diff)}). Expected if one is a staging copy that feeds nothing.",
                "Confirm the difference is intended.", "config")


def compare_findings(rep, a, b, data):
    changes = data.get("changes") if isinstance(data, dict) else None
    if not isinstance(changes, list):
        return False
    groups = {}
    for ch in changes:
        if not isinstance(ch, dict):
            continue
        obj = str(ch.get("object_type") or "?")
        keys = ch.get("keys") if isinstance(ch.get("keys"), dict) else {}
        label = str(keys.get("name") or ch.get("display_name") or "/".join(f"{k}={v}" for k, v in sorted(keys.items())))
        groups.setdefault((obj, str(ch.get("action") or "?")), []).append(label)
    for (obj, action), labels in sorted(groups.items()):
        pr = "high" if obj == "schema.identifier" else "low" if obj == "destination" else "medium"
        rep.add(pr, "configuration drift", a, None, f"{a} vs {b} (compare tool)",
                f"{len(labels)} {obj} change(s) '{action}' from {a} to {b}: {short(labels)}.",
                "Align the pair, or confirm the difference is intended.", "config")
    return True


# ----------------------------------------------------------------------------------------------

def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--collections", required=True, help="saved search_item_collections list (no collection_name)")
    ap.add_argument("--config", action="append", default=[], type=lambda t: keyed(t, "--config"),
                    help="NAME[:TYPE]=FILE: saved get_item_collection_configuration for a collection (and item type)")
    ap.add_argument("--fields", action="append", default=[], type=lambda t: keyed(t, "--fields"),
                    help="NAME[:TYPE]=FILE: saved search_item_collection_fields list (summary mode)")
    ap.add_argument("--records", action="append", default=[], type=lambda t: keyed(t, "--records"),
                    help="NAME[:TYPE]=FILE: saved search_item_collection_records list page (repeat per page)")
    ap.add_argument("--system", action="append", default=[], type=lambda t: keyed(t, "--system"),
                    help="NAME[:TYPE]=FILE: saved get_datahub_system_configuration (built-in field names)")
    ap.add_argument("--jobs", action="append", default=[], help="saved search_datahub_jobs result (repeatable)")
    ap.add_argument("--catalogs", help="saved search_datahub_catalogs list for a project in this workspace")
    ap.add_argument("--pair", action="append", default=[], type=pair_arg,
                    help="A,B: compare these two collections' configurations (base A)")
    ap.add_argument("--compare", action="append", default=[], type=compare_arg,
                    help="A,B=FILE: saved compare_item_collection_configurations result, base A, reference B")
    ap.add_argument("--no-auto-pair", action="store_true", help="only compare the pairs given with --pair")
    ap.add_argument("--today", type=today_arg, help="audit date YYYY-MM-DD (default: today in UTC)")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    today = a.today or datetime.now(timezone.utc).date()
    rep = Report()

    data, err = unwrap(a.collections, load(a.collections))
    if err:
        fail(f"{a.collections}: search_item_collections returned an error: {err}")
    colls = {}
    for c in as_list(data):
        if c.get("name"):
            colls[c["name"]] = c
    if not colls:
        fail(f"{a.collections}: no collections found; is this a search_item_collections list?")
    coll_ids = {str(c.get("_id") or c.get("id")): n for n, c in colls.items() if c.get("_id") or c.get("id")}
    types_by_coll = {n: collection_types(c) for n, c in colls.items()}

    def by_key(items, what):
        out = {}
        for key, path in items:
            payload, e = unwrap(path, load(path))
            if e:
                rep.not_checked.append(f"{what} for {key[0]}:{key[1]}: the tool returned an error ({e}).")
                out.setdefault(key, None)
                continue
            out.setdefault(key, []).append(payload)
        return out

    configs = {}
    for key, payloads in by_key(a.config, "Configuration").items():
        if payloads:
            cfg = payloads[-1]
            if not isinstance(cfg, dict):
                fail(f"configuration for {key[0]}:{key[1]} isn't an object.")
            configs[key] = parse_config(cfg)
    fields = {k: field_tool_stats([f for p in (v or []) for f in as_list(p)]) for k, v in by_key(a.fields, "Fields").items()
              if v is not None}
    records = {k: [r for p in v for r in as_list(p)] for k, v in by_key(a.records, "Records").items() if v is not None}
    system = {}
    for key, payloads in by_key(a.system, "System configuration").items():
        names = set()
        for p in payloads or []:
            sch = p.get("schema") if isinstance(p, dict) else None
            for att in (sch or {}).get("attributes") or []:
                if isinstance(att, dict) and att.get("name"):
                    names.add(att["name"])
        system[key] = names

    for key in sorted(set(configs) | set(fields) | set(records) | set(system)):
        if key[0] not in colls:
            fail(f"{key[0]} isn't in the collections list; check the name before NAME=FILE.")

    # Item types and collections.
    table = []
    for name in sorted(colls):
        tps = types_by_coll[name]
        if not tps:
            rep.add("medium", "collection without item types", name, None, name,
                    "The collection has no item types, so it can't hold data.",
                    "Add an item type or retire the collection.", "config")
        for t, (iclass, dest) in sorted(tps.items()):
            if destinations_empty(dest):
                rep.add("low", "item type feeds nothing", name, t, t,
                        "This item type has no Engagement or Discovery destination, so nothing downstream reads it.",
                        "Add a destination if it should be used; otherwise consider removing it.", "config")

    for key in sorted(set(configs) | set(records) | set(fields)):
        coll, t = key
        cfg = configs.get(key)
        recs = records.get(key)
        n, fill, kinds = sample_stats(recs or [])
        check_item_type(rep, coll, t, cfg, n, fill, kinds, fields.get(key, {}), system.get(key, set()),
                        recs is not None, key in fields)
        if cfg and cfg["unreadable_idents"]:
            rep.not_checked.append(f"{coll}:{t}: {cfg['unreadable_idents']} identifier definition(s) name no field the "
                                   "script recognises; check them by hand.")
        if cfg and unknown_types(cfg["attrs"]):
            rep.not_checked.append(f"{coll}:{t}: type checks skipped for data types {', '.join(unknown_types(cfg['attrs']))} "
                                   "(not in type_map).")
        if recs is not None and 0 < n < RULES["min_sample"]:
            rep.not_checked.append(f"{coll}:{t}: fill rates are rough, only {n} records sampled (see min_sample).")
        if cfg is None:
            rep.not_checked.append(f"{coll}:{t}: no configuration passed, so required, unused and type checks didn't run.")
    for name in sorted(colls):
        for t in sorted(types_by_coll[name]):
            if (name, t) not in records:
                rep.not_checked.append(f"{name}:{t}: no records sample, so fill rates and sampled types weren't checked.")
            if (name, t) not in configs and (name, t) not in fields:
                rep.not_checked.append(f"{name}:{t}: no configuration passed, so required, unused and type checks didn't run.")

    latest = {}
    jobs = []
    for path in a.jobs:
        payload, e = unwrap(path, load(path))
        if e:
            rep.not_checked.append(f"Jobs ({path}): the tool returned an error ({e}).")
            continue
        jobs += as_list(payload)
    if a.jobs:
        latest = check_jobs(rep, jobs, colls, today)
    else:
        rep.not_checked.append("Job health and freshness: no --jobs file.")

    linked = set()
    if a.catalogs:
        payload, e = unwrap(a.catalogs, load(a.catalogs))
        if e:
            rep.not_checked.append(f"Catalog links: search_datahub_catalogs returned an error ({e}).")
        else:
            linked = check_catalogs(rep, as_list(payload), colls, coll_ids, types_by_coll)
    else:
        rep.not_checked.append("Catalog links: no --catalogs file.")

    # Pairs.
    pairs = list(dict.fromkeys(a.pair + ([] if a.no_auto_pair else auto_pairs(colls))))
    compared = []
    tool_pairs = set()
    for (x, y), path in a.compare:
        payload, e = unwrap(path, load(path))
        if e:
            rep.not_checked.append(f"Compare {x} vs {y}: the tool returned an error ({e}).")
        elif compare_findings(rep, x, y, payload):
            tool_pairs.add((x, y))
            compared.append({"base": x, "reference": y, "source": "compare tool"})
    for x, y in pairs:
        if x not in colls or y not in colls:
            fail(f"--pair {x},{y}: both must be in the collections list.")
        if (x, y) in tool_pairs:
            continue
        shared = sorted(t for (c, t) in configs if c == x and (y, t) in configs)
        if not shared:
            rep.not_checked.append(f"Drift {x} vs {y}: pass --config for the same item type of both.")
            continue
        for t in shared:
            drift(rep, x, y, configs[(x, t)], configs[(y, t)], t)
        compared.append({"base": x, "reference": y, "source": "configurations", "item_types": shared})

    for name in sorted(colls):
        tps = types_by_coll[name]
        all_dest = [d for _, d in tps.values()]
        if a.catalogs and name not in linked and all(destinations_empty(d) is True for d in all_dest) and all_dest:
            rep.add("low", "collection unused downstream", name, None, name,
                    "No catalog links to it and its item types have no destinations.",
                    "Retire it if nothing else reads it.", "downstream")
        row = {"collection": name, "item_types": sorted(tps), "records_sampled": {}, "configured_attributes": {},
               "latest_successful_data_job": latest.get(name), "catalog_linked": (name in linked) if a.catalogs else None}
        for t in sorted(tps):
            if (name, t) in records:
                row["records_sampled"][t] = len(records[(name, t)])
            if (name, t) in configs:
                row["configured_attributes"][t] = len(configs[(name, t)]["attrs"])
        table.append(row)

    findings = sorted(rep.findings, key=lambda f: (PRIORITIES.index(f["priority"]), f["check"], f["collection"] or "",
                                                   f["item_type"] or "", f["subject"] or ""))
    out = {"ok": True, "today": today.isoformat(),
           "counts": {p: sum(f["priority"] == p for f in findings) for p in PRIORITIES},
           "findings": findings, "collections": table, "pairs_compared": compared,
           "not_checked": sorted(set(rep.not_checked))}
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"Can't write {a.out}: {e.strerror or e}")
    print(text)


if __name__ == "__main__":
    main()
