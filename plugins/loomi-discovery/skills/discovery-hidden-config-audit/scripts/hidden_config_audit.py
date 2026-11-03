#!/usr/bin/env python3
"""Audit Bloomreach Discovery audiences and API parameter overrides: settings that silently change results.

Usage:
  python3 hidden_config_audit.py --audiences audiences.json [--audience-rules 12753=rules_12753.json ...]
         [--api-params api_params.json ...] [--rules ranking_rules.json ...] --today 2026-11-03 [--out audit.json]

--audiences      saved list_discovery_audiences result.
--audience-rules <audience id>=<file>: a rule list fetched with audience_ids=<that id> (site search, category
                 or global ranking rules, or media rules). Repeat per audience and per list. Rule lists don't
                 name the audience (audienceName is null), so the id is given here.
--api-params     saved list_api_params result (repeat per site).
--rules          saved unfiltered rule lists (ranking or facet), used to say what a global override can affect.
--today          the audit date, so results don't depend on when the script runs.

Prints JSON: findings sorted into fix_now, clean_up and review; protected items; the personalised-rule map
(rule -> audience) that discovery-rule-audit needs to tell personalisation from duplicates; audiences whose
rulesAffected the given lists don't account for, and used audiences whose rule lists weren't given; and the
Engagement segments audiences depend on.

Within an audience, values in one dimension are treated as alternatives (OR) and different dimensions as
all required (AND). Thresholds and word lists are in references/rules.json. Standard library only; no network.
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# The thresholds live in references/rules.json, next to this script's folder.
RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
PRIORITIES = ("fix_now", "clean_up", "review")
NEGATIVE = {"IS_NOT", "NOT_CONTAIN", "DOES_NOT_CONTAIN", "NOT_CONTAINS"}


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {d.get('error') or 'no error text'}. "
                 "This check couldn't run; don't treat it as 'nothing found'.")
    while isinstance(data, dict) and isinstance(data.get("result"), (dict, list)):
        data = data["result"]
    while isinstance(data, dict) and isinstance(data.get("data"), (dict, list)):
        data = data["data"]
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        fail(f"{path}: expected a list of records.")
    return [r for r in data if isinstance(r, dict)]


def day(ms):
    """Unix milliseconds (or seconds) -> date, or None."""
    if not isinstance(ms, (int, float)) or ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000 if ms > 1e11 else ms, timezone.utc).date()


def has_phrase(name, phrases):
    low = (name or "").lower()
    return any(p in low for p in phrases)


def has_word(name, words):
    return bool(set(re.findall(r"[a-z]+", (name or "").lower())) & set(words))


class Report:
    def __init__(self):
        self.findings, self.protected = [], []

    def add(self, priority, area, item, issue, evidence, action):
        self.findings.append({"priority": priority, "area": area, "id": item.get("id"),
                              "name": (item.get("audienceName") or item.get("name") or "").strip() or None,
                              "issue": issue, "evidence": evidence, "action": action})


# ----------------------------------------------------------------------------------------------
# Audiences

def conditions(aud):
    """[(dimension internal name, external name, type, match type, raw value)] for one audience."""
    out = []
    for dim in aud.get("dimensionList") or []:
        for v in dim.get("dimensionValueList") or []:
            match = ((v.get("matchtype") or {}).get("internalName") or "").upper()
            out.append((dim.get("internalName"), dim.get("externalName") or dim.get("internalName"),
                        dim.get("type"), match, v.get("internalValue") if v.get("internalValue") is not None
                        else v.get("externalValue")))
    return out


def norm(value):
    return str(value or "").strip().lower()


def cant_match_reasons(aud):
    """Reasons an audience can never (or always) match: conditions a real request can't meet."""
    reasons = []
    by_dim = {}
    for dim, ext, _, match, value in conditions(aud):
        by_dim.setdefault(dim, []).append((match, value))
        raw = "" if value is None else str(value)
        if not raw.strip():
            reasons.append(f"{ext}: empty value")
        elif dim in RULES["url_dimensions"]:
            if raw != raw.strip():
                reasons.append(f"{ext} value {raw!r} has a leading or trailing space, which a URL never contains")
            elif " " in raw:
                reasons.append(f"{ext} value {raw!r} contains a space; URLs encode spaces as %20 or +")
    for dim, items in by_dim.items():
        pos = {norm(v) for m, v in items if m not in NEGATIVE}
        neg = {norm(v) for m, v in items if m in NEGATIVE}
        both = sorted(pos & neg)
        if both:
            reasons.append(f"both IS and IS NOT {both[0]!r} on the same dimension: it matches everyone or no one")
    if not conditions(aud):
        reasons.append("no conditions at all")
    return reasons


def risky_values(aud):
    """Conditions that probably match more, or less, than intended."""
    notes = []
    for dim, ext, _, match, value in conditions(aud):
        raw = str(value or "")
        if dim not in RULES["url_dimensions"] or not raw.strip():
            continue
        if match == "CONTAIN_MATCH" and len(raw.strip()) < RULES["min_contains_chars"]:
            notes.append(f"{ext} CONTAINS {raw.strip()!r} is short, so it also matches unrelated URLs")
        if raw.strip().startswith("&"):
            notes.append(f"{ext} value {raw.strip()!r} starts with &, so it misses URLs where that parameter comes "
                         "first (after ?)")
        if any(ord(c) > 127 for c in raw):
            notes.append(f"{ext} value {raw.strip()!r} has accented characters, which URLs percent-encode")
    return notes


def check_audiences(rep, audiences, audience_rules, today):
    used = {a["id"]: (a.get("rulesAffected") or 0) for a in audiences}
    for a in audiences:
        name = (a.get("audienceName") or "").strip()
        aid, n_rules = a.get("id"), used[a.get("id")]
        rules = audience_rules.get(aid, [])
        protected = has_phrase(name, RULES["protected_phrases"])
        if protected:
            rep.protected.append({"area": "audience", "id": aid, "name": name, "rules_affected": n_rules})
        broken = cant_match_reasons(a)
        live = [r for r in rules if r.get("enabled") and r.get("durationTag") != "expired"]
        if broken:
            if live:
                rep.add("fix_now", "audience", a, "Audience can't match as written, so its rules never fire",
                        "; ".join(broken) + f". Enabled rules: {', '.join(str(r.get('id')) for r in live)}",
                        "Fix the condition (copy the value from a real URL), then check the rules with discovery-change-qa")
            elif n_rules:
                rep.add("fix_now", "audience", a, "Audience can't match as written, but rules use it",
                        "; ".join(broken) + f". rulesAffected: {n_rules}",
                        "Fix the condition, or move its rules to a working audience")
            elif not protected:
                rep.add("clean_up", "audience", a, "Unused audience that can't match anyway", "; ".join(broken),
                        "Delete it in the Discovery dashboard")
            continue
        notes = risky_values(a)
        if notes and n_rules:
            rep.add("review", "audience", a, "Condition probably matches more or less than intended",
                    "; ".join(notes) + f". rulesAffected: {n_rules}",
                    "Rewrite the value to match exactly the URLs you mean (e.g. a whole parameter such as "
                    "segment=vic), then re-test its rules with discovery-change-qa")
        if n_rules == 0 and not protected:
            created = day(a.get("createdAt"))
            age = (today - created).days if created else None
            test = has_word(name, RULES["test_name_words"])
            if age is not None and age < RULES["unused_min_age_days"]:
                rep.add("review", "audience", a, "New audience not used by any rule yet",
                        f"created {created}, {age} days ago", "Check with its owner that it's about to be used")
            else:
                rep.add("clean_up", "audience", a, "Unused " + ("test " if test else "") + "audience",
                        f"rulesAffected 0; created {created or 'unknown'}"
                        + ("; " + "; ".join(notes) if notes else ""), "Delete it in the Discovery dashboard")
        elif rules and not live:
            rep.add("clean_up", "audience", a, "Audience only drives disabled or expired rules",
                    f"{len(rules)} rule(s) found, none enabled and in date: "
                    + ", ".join(str(r.get("id")) for r in rules),
                    "Delete the old rules and the audience, or re-enable what's still wanted")
    check_audience_pairs(rep, audiences)


def check_audience_pairs(rep, audiences):
    signatures = {}
    for a in audiences:
        sig = tuple(sorted((d, m, norm(v)) for d, _, _, m, v in conditions(a)))
        if sig:
            signatures.setdefault(sig, []).append(a)
    for group in signatures.values():
        if len(group) > 1:
            names = ", ".join(f"{g.get('id')} ({(g.get('audienceName') or '').strip()})" for g in group)
            in_use = [g for g in group if g.get("rulesAffected")]
            rep.add("fix_now" if len(in_use) > 1 else "clean_up", "audience", group[0],
                    "Audiences with identical conditions", names,
                    "Keep one, move its rules over and delete the others" if len(in_use) > 1
                    else "Delete the unused copies")
    for a in audiences:
        if not a.get("rulesAffected"):
            continue
        for b in audiences:
            if a is b:
                continue
            for da, _, _, ma, va in conditions(a):
                for db, ext, _, mb, vb in conditions(b):
                    x, y = norm(va), norm(vb)
                    if (da == db and ma == "CONTAIN_MATCH" and mb not in NEGATIVE and x and y and x != y
                            and x in y):
                        rep.add("review", "audience", a, "Overlaps another audience",
                                f"{ext} CONTAINS {x!r} also matches every visitor of audience {b.get('id')} "
                                f"({(b.get('audienceName') or '').strip()}), whose value is {y!r}",
                                "Make the values distinct so each visitor gets the intended rules")


def personalised_map(audiences, audience_rules):
    names = {a.get("id"): (a.get("audienceName") or "").strip() for a in audiences}
    rows, unaccounted = [], []
    for aid, rules in audience_rules.items():
        for r in rules:
            rows.append({"rule_id": r.get("id"), "rule_type": r.get("ruleType"),
                         "queries": [q.get("query") for q in r.get("queries") or []],
                         "audience_id": aid, "audience": names.get(aid), "enabled": r.get("enabled"),
                         "duration": r.get("durationTag")})
    for a in audiences:
        found = len(audience_rules.get(a.get("id"), []))
        if a.get("id") in audience_rules and (a.get("rulesAffected") or 0) > found:
            unaccounted.append({"audience_id": a.get("id"), "audience": names.get(a.get("id")),
                                "rules_affected": a.get("rulesAffected"), "found_in_lists": found})
    rows.sort(key=lambda r: (str(r["queries"]), str(r["audience_id"])))
    not_fetched = [{"audience_id": a.get("id"), "audience": names.get(a.get("id")), "rules_affected": a.get("rulesAffected")}
                   for a in audiences if a.get("rulesAffected") and a.get("id") not in audience_rules]
    return rows, unaccounted, not_fetched


def engagement_dependencies(audiences):
    deps = {}
    for a in audiences:
        for d, ext, typ, _, _ in conditions(a):
            if typ == "engagement":
                deps.setdefault(ext, set()).add(a.get("id"))
    return [{"engagement_segment": k, "audiences": sorted(v)} for k, v in sorted(deps.items())]


# ----------------------------------------------------------------------------------------------
# API parameter overrides

def override_params(item):
    """[(param, value)] from an override record, or None if it holds none we can read. The record shape isn't
    documented, so this accepts a {param: value} map or a list of {name/param/key, value} entries, under
    customizationItems, params, parameters or apiParams."""
    section = next((item[k] for k in ("customizationItems", "params", "parameters", "apiParams") if item.get(k)), None)
    found = []

    def take(obj):
        if isinstance(obj, list):
            for v in obj:
                take(v)
        elif isinstance(obj, dict):
            name = next((obj[k] for k in ("param", "paramName", "parameter", "name", "key") if isinstance(obj.get(k), str)), None)
            if name and any(k in obj for k in ("value", "paramValue", "values")):
                found.append((name, obj.get("value", obj.get("paramValue", obj.get("values")))))
                return
            for k, v in obj.items():
                if isinstance(v, (str, int, float, bool)):
                    found.append((k, v))
                else:
                    take(v)

    take(section)
    return found or None


def check_overrides(rep, overrides, rules, today):
    ranking = sum(1 for r in rules if r.get("enabled") and r.get("ruleType") == "ranking")
    facets = sum(1 for r in rules if r.get("enabled") and r.get("ruleType") == "facet")
    seen = {}
    for o in overrides:
        name = (o.get("name") or "").strip()
        if has_phrase(name, RULES["protected_phrases"]):
            rep.protected.append({"area": "api_param", "id": o.get("id"), "name": name})
        queries = [q.get("query") for q in o.get("queries") or [] if isinstance(q, dict)]
        scope = "every search and category request" if not queries or "*" in queries else \
            "queries " + ", ".join(repr(q) for q in queries[:5])
        enabled, expired = o.get("enabled") is not False, o.get("durationTag") == "expired"
        modified = day(o.get("lastModifiedAt") or o.get("modifiedAt"))
        age = (today - modified).days if modified else None
        params = override_params(o)
        if enabled and expired:
            rep.add("fix_now", "api_param", o, "Expired override still enabled", f"durationTag expired; applies to {scope}",
                    "Disable it in the Discovery dashboard")
            continue
        if not enabled:
            if age is not None and age >= RULES["stale_days"]:
                rep.add("clean_up", "api_param", o, "Old disabled override", f"disabled; last changed {modified}",
                        "Delete it in the Discovery dashboard")
            continue
        if params is None:
            rep.add("review", "api_param", o, "Couldn't read which parameters this override sets",
                    f"applies to {scope}", "Open it in the Discovery dashboard and note the parameter and value")
            continue
        for p, v in params:
            key = str(p).strip().lower()
            seen.setdefault(key, []).append(o)
            if key in RULES["override_fix_now_params"]:
                rep.add("fix_now", "api_param", o, f"Overrides {p} = {v!r}",
                        f"{RULES['override_fix_now_params'][key]}; applies to {scope}",
                        "Remove the override unless it was put there on purpose, and test with discovery-change-qa")
            elif key in RULES["override_review_params"]:
                extra = ""
                if key == "sort" and ranking:
                    extra = f"; {ranking} enabled ranking rule(s) in the lists given may have no effect under it"
                if key in ("fq", "efq") and facets:
                    extra = f"; {facets} enabled facet rule(s) in the lists given work on the filtered set only"
                rep.add("review", "api_param", o, f"Overrides {p} = {v!r}",
                        f"{RULES['override_review_params'][key]}; applies to {scope}{extra}",
                        "Confirm it's still wanted; document why in its name")
            elif not name and age is not None and age >= RULES["stale_days"]:
                rep.add("review", "api_param", o, f"Unnamed old override of {p} = {v!r}",
                        f"last changed {modified}; applies to {scope}", "Name it, or remove it if nobody knows why it's there")
    for key, items in seen.items():
        if len({id(i) for i in items}) > 1:
            rep.add("fix_now", "api_param", items[0], f"{key} is overridden by more than one enabled override",
                    "overrides " + ", ".join(str(i.get("id")) for i in items), "Keep one")


def pair(spec):
    if "=" not in spec:
        fail(f"--audience-rules needs <audience id>=<file>, got {spec!r}.")
    aid, path = spec.split("=", 1)
    try:
        return int(aid.strip()), path
    except ValueError:
        fail(f"--audience-rules: {aid!r} isn't a numeric audience id.")


def when(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {text!r}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--audiences", help="saved list_discovery_audiences result")
    ap.add_argument("--audience-rules", action="append", default=[], help="<audience id>=<rule list filtered by it>")
    ap.add_argument("--api-params", action="append", default=[], help="saved list_api_params result (repeat per site)")
    ap.add_argument("--rules", action="append", default=[], help="saved unfiltered rule list (ranking or facet)")
    ap.add_argument("--today", type=when, required=True, help="audit date, YYYY-MM-DD")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    if not a.audiences and not a.api_params:
        fail("Give --audiences, --api-params or both.")
    rep = Report()
    audiences = read(a.audiences) if a.audiences else []
    audience_rules = {}
    for spec in a.audience_rules:
        aid, path = pair(spec)
        audience_rules.setdefault(aid, []).extend(read(path))
    check_audiences(rep, audiences, audience_rules, a.today)
    overrides = [o for p in a.api_params for o in read(p)]
    rules = [r for p in a.rules for r in read(p)]
    check_overrides(rep, overrides, rules, a.today)
    personalised, unaccounted, not_fetched = personalised_map(audiences, audience_rules)
    order = {p: i for i, p in enumerate(PRIORITIES)}
    findings = sorted(rep.findings, key=lambda f: (order[f["priority"]], f["area"], str(f["id"])))
    out = {"ok": True, "today": a.today.isoformat(),
           "summary": {"audiences": len(audiences), "audiences_unused": sum(1 for x in audiences if not x.get("rulesAffected")),
                       "api_param_overrides": len(overrides),
                       "api_param_overrides_enabled": sum(1 for o in overrides if o.get("enabled") is not False),
                       **{p: sum(1 for f in findings if f["priority"] == p) for p in PRIORITIES}},
           "findings": findings, "protected": rep.protected, "personalised_rules": personalised,
           "audiences_not_fully_accounted": unaccounted, "audience_rules_not_fetched": not_fetched, "engagement_dependencies": engagement_dependencies(audiences)}
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
