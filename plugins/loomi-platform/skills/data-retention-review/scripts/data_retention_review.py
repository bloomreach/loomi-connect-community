#!/usr/bin/env python3
"""Compare a Bloomreach Engagement project's event retention rules with the lookback windows its analytics read.

Usage:
  python3 data_retention_review.py --retention retention.json [--definition KIND=detail.json ...]
         [--event-schema event-schema.json] [--customer-schema customer-property-schema.json]
         [--no-skill-needs] [--today 2026-11-04] [--out review.json]

--retention        saved get_data_retention_rules result (required).
--definition       KIND=FILE: a saved detail (or list of details) of a definition that reads events. KIND is one of
                   aggregate, running_aggregate, segmentation, event_segmentation, customer_filter, expression,
                   prediction, report, funnel, trend, scenario. Repeat per file.
--event-schema     saved get_event_schema result: the event types and their property names.
--customer-schema  saved get_customer_property_schema result: customer property names (values are never read).
--no-skill-needs   don't compare retention with the windows this repository's skills read (skill_needs).
--today            the review date (default: today in UTC); absolute date windows are measured from it.

Prints JSON: findings sorted by priority (high, medium, low), each with what's wrong and the change to consider; a
table of each event type's retention against the longest window that reads it; every window found; and what
couldn't be checked. Only names are printed, never customer or event values.

Unit lengths, word lists, skill needs and thresholds are in references/rules.json. Standard library only; no
network access. This is a data-management check, not legal advice.
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from fractions import Fraction
from pathlib import Path

# The rules live in references/rules.json, next to this script's folder.
RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
PRIORITIES = ("high", "medium", "low")
KINDS = ("aggregate", "running_aggregate", "segmentation", "event_segmentation", "customer_filter", "expression",
         "prediction", "report", "funnel", "trend", "scenario")
URL = re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s\"'<>]+", re.I)
# Errors that stop the run: about the project or organisation, 401, or a 429 that persisted.
CONTEXT_WORDS = ("project", "organisation", "organization", "unauthori", "401", "429", "rate limit",
                 "too many requests")
# A 403 on one kind of definition (search_predictions is often denied) only means that kind isn't checked.
DENIED_WORDS = ("403", "forbidden", "access_denied", "access denied", "permission", "not allowed")
# 'type' values that are structure, not event names.
NOT_EVENTS = {"event", "events", "funnel_steps", "attribute", "property", "timestamp", "constant", "date", "string",
              "number", "boolean", "list", "aggregate", "expression", "segmentation", "customer_filter", "consent",
              "id", "and", "or", "not", "static", "dynamic", "none", "running_aggregate", "prediction", "all", "any",
              "first", "last", "count", "sum", "average", "value", "step", "condition", "filter", "formula"}
INF = None  # a lifetime window or a rule that keeps events forever
ALL_OTHERS = "(every event without an override)"


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def redact(text):
    return URL.sub("<url>", str(text or "no error text")).strip()[:200]


def load(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            err = d.get("error")
            low = str(err or "").lower()
            hard = any(w in low for w in ("401", "unauthori", "429", "rate limit", "too many requests"))
            if what in KINDS and not hard and any(w in low for w in DENIED_WORDS):
                return None, redact(err)  # this kind isn't checked; the run carries on
            if hard or any(w in low for w in CONTEXT_WORDS):
                fail(f"{path}: Loomi Connect returned an error about the project or access: {redact(err)} "
                     "Stop and check the project and the user's access.")
            return None, redact(err)
    if isinstance(data, dict) and isinstance(data.get("result"), (dict, list)) and what != "retention":
        data = data["result"]
    elif isinstance(data, dict) and isinstance(data.get("result"), dict) and "event_overrides" in data["result"]:
        data = data["result"]
    if isinstance(data, dict) and isinstance(data.get("data"), (dict, list)):
        data = data["data"]
    return data, None


def today_arg(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {text!r}")


def definition_arg(text):
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"--definition must look like KIND=FILE, got {text!r}")
    kind, path = text.split("=", 1)
    kind = kind.strip().lower()
    if kind not in KINDS:
        raise argparse.ArgumentTypeError(f"unknown kind {kind!r}; use one of {', '.join(KINDS)}")
    return kind, path


def short(names):
    names = sorted(set(names))
    n = RULES["list_limit"]
    return ", ".join(names[:n]) + (f" and {len(names) - n} more" if len(names) > n else "")


def unit_days(units):
    table = RULES["unit_days"]
    u = str(units or "").strip().lower()
    if u in table:
        return Fraction(table[u])
    if u.rstrip("s") + "s" in table:
        return Fraction(table[u.rstrip("s") + "s"])
    return None


def duration_days(d):
    """Days in a {'count', 'units'} duration, or None if it can't be read."""
    if not isinstance(d, dict) or isinstance(d.get("count"), bool) or not isinstance(d.get("count"), (int, float)):
        return None
    per = unit_days(d.get("units"))
    return None if per is None else Fraction(d["count"]).limit_denominator(10**6) * per


def show(days):
    if days is INF:
        return "forever"
    whole = round(float(days), 1)
    text = str(int(whole)) if whole == int(whole) else str(whole)
    return f"{text} day" if text == "1" else f"{text} days"


# ----------------------------------------------------------------------------------------------
# Retention

def parse_retention(data):
    if not isinstance(data, dict):
        fail("--retention: expected a get_data_retention_rules object.")
    default = INF
    if data.get("default_retention_enabled") is True:
        default = duration_days(data.get("default_duration"))
        if default is None:
            fail("--retention: default retention is enabled but its duration can't be read.")
    overrides = {}
    for o in data.get("event_overrides") or []:
        if not isinstance(o, dict) or not o.get("event_type"):
            continue
        if o.get("retention_enabled") is True:
            d = duration_days(o.get("duration"))
            if d is None:
                fail(f"--retention: the rule for {o['event_type']!r} is enabled but its duration can't be read.")
            overrides[o["event_type"]] = d
        else:
            overrides[o["event_type"]] = INF
    return default, overrides


def kept(event, default, overrides):
    return overrides.get(event, default)


# ----------------------------------------------------------------------------------------------
# Windows in definitions

def own_events(node):
    """Event type names this dict names directly (not in children)."""
    out = set()
    ev = node.get("event")
    if isinstance(ev, dict) and isinstance(ev.get("type"), str):
        out.add(ev["type"])
    elif isinstance(ev, str):
        out.add(ev)
    for k in ("event_type", "target_event", "event_name", "target_event_type"):
        if isinstance(node.get(k), str) and node[k]:
            out.add(node[k])
    for k in ("event_types", "events"):
        for v in node.get(k) or [] if isinstance(node.get(k), list) else []:
            if isinstance(v, str):
                out.add(v)
    for step in node.get("steps") or [] if isinstance(node.get("steps"), list) else []:
        if isinstance(step, dict):
            for k in ("event_type", "type", "name"):
                v = step.get(k)
                if isinstance(v, str) and v and v.lower() not in NOT_EVENTS:
                    out.add(v)
                    break
    return {e for e in out if e.lower() not in NOT_EVENTS}


def events_in(node):
    out = set()
    if isinstance(node, dict):
        out |= own_events(node)
        for v in node.values():
            out |= events_in(v)
    elif isinstance(node, list):
        for v in node:
            out |= events_in(v)
    return out


def date_window(df, today):
    """(mode, days) for a date filter: lifetime, rolling or absolute; None if it can't be read."""
    if df.get("enabled") is not True:
        return "lifetime", INF
    if df.get("absolute") is True:
        start = df.get("from_date")
        if isinstance(start, bool) or not isinstance(start, (int, float)):
            return None
        secs = start / 1000 if start > 1e11 else start
        try:
            start_day = datetime.fromtimestamp(secs, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
        return "absolute", Fraction(max((today - start_day).days, 0))
    days = duration_days(df.get("duration"))
    if days is None:
        return None
    off = df.get("offset")
    extra = duration_days(off) if isinstance(off, dict) else None
    return "rolling", days + (extra or 0)


UNREADABLE = "unreadable"  # a timestamp condition whose unit, amount or operator isn't understood


def timestamp_window(node):
    """(mode, days) for an event timestamp condition such as 'in the last 30 days' or 'more than 3 months ago';
    UNREADABLE for a timestamp condition that can't be read (unknown unit or operator); None when it isn't one."""
    att, con = node.get("attribute"), node.get("constraint")
    if not (isinstance(att, dict) and att.get("type") == "timestamp" and isinstance(con, dict)):
        return None
    amount = con.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return UNREADABLE
    days = duration_days({"count": amount, "units": con.get("units")})
    if days is None:
        return UNREADABLE
    op = str(con.get("operator") or "").lower()
    if op in ("more than", "older than", "before") or (op.startswith("more") and con.get("tense") == "ago"):
        return "older_than", days
    if "last" in op or op in ("less than", "within"):
        return "in_last", days
    return UNREADABLE


def find_windows(kind, defn, today, problems):
    found = []
    all_events = events_in(defn)

    def walk(node, inherited):
        if isinstance(node, list):
            for v in node:
                walk(v, inherited)
            return
        if not isinstance(node, dict):
            return
        mine = events_in(node) if own_events(node) else set()
        here = mine or inherited
        for k in ("date_filter", "date"):
            df = node.get(k)
            if not (isinstance(df, dict) and "enabled" in df and ("duration" in df or "from_date" in df)):
                continue
            if kind == "report" and k == "date_filter" and df.get("enabled") is not True:
                continue  # a report member's disabled filter follows the report-wide date
            w = date_window(df, today)
            evs = events_in(node) or here or all_events
            if w is None:
                problems.append(f"{kind} {defn.get('name')!r}: a date filter couldn't be read.")
            elif evs:
                found.append((w[0], w[1], evs))
        tw = timestamp_window(node)
        if tw == UNREADABLE:
            problems.append(f"{kind} {defn.get('name')!r}: a timestamp condition couldn't be read.")
        elif tw and (here or all_events):
            found.append((tw[0], tw[1], here or all_events))
        for k, v in node.items():
            if k in ("date_filter", "date"):
                continue
            walk(v, here)

    walk(defn, set())
    return found


# ----------------------------------------------------------------------------------------------
# Personal-looking names

def name_words(name):
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(name))
    words = [w for w in re.split(r"[^a-z]+", spaced.lower()) if w]
    return words + [a + b for a, b in zip(words, words[1:])]


def sensitivity(name):
    words = name_words(name)

    def hit(lst):
        for w in words:
            for p in lst:
                if w == p or (len(p) >= 4 and w.startswith(p)):
                    return True
        return False

    if hit(RULES["personal_words"]["high"]):
        return "high"
    if hit(RULES["not_personal_words"]):
        return None
    for level in ("medium", "low"):
        if hit(RULES["personal_words"][level]):
            return level
    return None


class Report:
    def __init__(self):
        self.findings, self.not_checked = [], []

    def add(self, priority, check, subject, issue, change, kind=None, name=None):
        self.findings.append({"priority": priority, "check": check, "subject": subject, "kind": kind,
                              "name": name, "issue": issue, "change": change})


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--retention", required=True, help="saved get_data_retention_rules result")
    ap.add_argument("--definition", action="append", default=[], type=definition_arg,
                    help="KIND=FILE: saved definition detail that reads events (repeatable)")
    ap.add_argument("--event-schema", help="saved get_event_schema result")
    ap.add_argument("--customer-schema", help="saved get_customer_property_schema result (names only are used)")
    ap.add_argument("--no-skill-needs", action="store_true", help="skip the windows this repository's skills read")
    ap.add_argument("--today", type=today_arg, help="review date YYYY-MM-DD (default: today in UTC)")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    today = a.today or datetime.now(timezone.utc).date()
    rep = Report()

    data, err = load(a.retention, "retention")
    if err:
        fail(f"{a.retention}: get_data_retention_rules returned an error: {err} The review can't run without it.")
    default, overrides = parse_retention(data)

    # Event schema.
    schema_events, event_props = None, {}
    if a.event_schema:
        es, err = load(a.event_schema, "events")
        if err:
            rep.not_checked.append(f"Event schema: the tool returned an error ({err}).")
        else:
            evs = es.get("events") if isinstance(es, dict) else es
            schema_events = set()
            for e in evs if isinstance(evs, list) else []:
                if isinstance(e, dict) and e.get("type"):
                    schema_events.add(e["type"])
                    props = set()
                    groups = e.get("properties") if isinstance(e.get("properties"), dict) else {}
                    for g in groups.values():
                        if isinstance(g, dict):
                            for p in g.get("properties") or []:
                                if isinstance(p, dict) and p.get("property"):
                                    props.add(p["property"])
                    event_props[e["type"]] = props
    else:
        rep.not_checked.append("Event types with no retention rule and personal data in events: no --event-schema file.")

    # Windows.
    windows, archived, problems = [], 0, []
    for kind, path in a.definition:
        payload, err = load(path, kind)
        if err:
            rep.not_checked.append(f"{kind} ({path}): the tool returned an error ({err}).")
            continue
        items = [payload] if isinstance(payload, dict) else [x for x in payload or [] if isinstance(x, dict)]
        for defn in items:
            if defn.get("archived") is True:
                archived += 1
                continue
            name = str(defn.get("name") or defn.get("_id") or defn.get("id") or "(unnamed)")
            for mode, days, evs in find_windows(kind, defn, today, problems):
                for ev in sorted(evs):
                    windows.append({"kind": kind, "name": name, "event": ev, "mode": mode, "days": days})
    rep.not_checked += problems
    if archived:
        rep.not_checked.append(f"{archived} archived definition(s) skipped.")
    if not a.definition:
        rep.not_checked.append("Windows in segmentations, aggregates, reports, funnels and predictions: no --definition files.")

    # 1. Windows longer than retention (one finding per definition and event, longest window).
    worst = {}
    for w in windows:
        ret = kept(w["event"], default, overrides)
        if ret is INF:
            continue
        key = (w["kind"], w["name"], w["event"])
        over = (w["mode"] == "lifetime" or (w["mode"] == "older_than" and w["days"] >= ret)
                or (w["mode"] not in ("lifetime", "older_than") and w["days"] > ret))
        if not over:
            continue
        rank = (w["mode"] == "older_than", w["mode"] != "lifetime", w["days"] or 0)
        if key not in worst or rank > worst[key][0]:
            worst[key] = (rank, w, ret)
    live = set(RULES["feeds_live_kinds"])
    for (kind, name, ev), (_, w, ret) in sorted(worst.items()):
        if w["mode"] == "lifetime":
            rep.add("medium" if kind in live else "low", "lifetime window on expiring events", ev,
                    f"{kind} '{name}' reads {ev} over all time, but {ev} is kept {show(ret)}, so 'all time' quietly "
                    f"means the last {show(ret)}.", "Accept and relabel it, or keep the event longer.", kind, name)
        elif w["mode"] == "older_than":
            rep.add("high" if kind in live else "medium", "window never satisfiable", ev,
                    f"{kind} '{name}' looks for {ev} more than {show(w['days'])} ago, but {ev} is deleted after "
                    f"{show(ret)}, so the condition can never be true.",
                    "Keep the event longer than the window, or change the condition.", kind, name)
        else:
            rep.add("high" if kind in live else "medium", "window longer than retention", ev,
                    f"{kind} '{name}' looks back {show(w['days'])} at {ev}, which is kept {show(ret)}: it under-counts.",
                    "Shorten the window to the retention, or keep the event longer.", kind, name)

    # 2. Windows this repository's skills read.
    needs = []
    if not a.no_skill_needs:
        for need in RULES["skill_needs"]:
            if need["event"] == "*":
                evs = sorted(ev for ev, r in overrides.items() if r is not INF)
                if default is not INF:
                    evs.append(ALL_OTHERS)
            elif schema_events is not None and need["event"] not in schema_events:
                continue  # the project doesn't track it, so the skill has nothing to read
            else:
                evs = [need["event"]]
            for ev in evs:
                ret = default if ev == ALL_OTHERS else kept(ev, default, overrides)
                needs.append({"event": ev, "days": Fraction(need["days"])})
                if ret is not INF and ret < need["days"]:
                    rep.add("medium", "skill window longer than retention", ev,
                            f"{need['skill']} reads {need['days']} days of {ev} ({need['why']}), but {ev} is kept "
                            f"{show(ret)}.", f"Expect {need['skill']} to under-count, or keep {ev} longer.",
                            "skill", need["skill"])

    # 3. Events kept far longer than anything reads.
    universe = set(overrides) | {w["event"] for w in windows} | (schema_events or set())
    rows, forever_unread, forever_short, long_kept = [], [], [], []
    for ev in sorted(universe):
        ret = kept(ev, default, overrides)
        reads = [w for w in windows if w["event"] == ev]
        uses = [w["days"] for w in reads] + [n["days"] for n in needs if n["event"] == ev
                                              or (n["event"] == ALL_OTHERS and ev not in overrides)]
        lifetime = any(w["mode"] == "lifetime" for w in reads)
        longest = INF if lifetime else (max(uses) if uses else Fraction(0))
        rows.append({"event": ev, "retention": show(ret), "rule": "override" if ev in overrides else "default",
                     "longest_window": "all time" if lifetime else (show(longest) if uses else "none found"),
                     "definitions_reading": len({(w["kind"], w["name"]) for w in reads}),
                     "in_schema": None if schema_events is None else ev in schema_events})
        if lifetime:
            continue
        limit = max(longest, Fraction(RULES["min_keep_days"])) * RULES["overkeep_factor"]
        if ret is not INF and ret <= limit:
            continue
        personal = sorted(p for p in event_props.get(ev, ()) if sensitivity(p) in ("high", "medium"))
        if personal:
            rep.add("medium", "personal data kept longer than used", ev,
                    f"{ev} is kept {show(ret)} and carries personal-looking properties ({short(personal)}); the "
                    f"longest window found reads {show(longest) if uses else 'none of it'}.",
                    "Set a retention rule for this event close to what you actually use, after checking with your "
                    "data protection lead.")
        elif ret is INF:
            (forever_short if uses else forever_unread).append(ev)
        else:
            long_kept.append(ev)
    if forever_unread:
        rep.add("low", "kept forever, nothing reads it", short(forever_unread),
                f"{len(forever_unread)} event type(s) have no retention rule and no window found reads them.",
                "Consider a retention rule (cost and privacy), once you've checked scenarios and exports don't need them.")
    if forever_short:
        rep.add("low", "kept forever, read briefly", short(forever_short),
                f"{len(forever_short)} event type(s) have no retention rule, although every window found reads them "
                "over a limited period.",
                "Consider a retention rule a little longer than the longest window.")
    if long_kept:
        rep.add("low", "kept much longer than read", short(long_kept),
                f"{len(long_kept)} event type(s) are kept more than {RULES['overkeep_factor']}x longer than any window "
                "found reads.", "Consider shortening their retention.")
    if schema_events is not None:
        stale = sorted(ev for ev in overrides if ev not in schema_events)
        if stale:
            rep.add("low", "rule for an unknown event", short(stale),
                    "Retention rules exist for event types the event schema doesn't list (renamed or never tracked).",
                    "Remove the rule, or fix the event name.")

    # 4. Customer properties that look personal: event retention never deletes them.
    props_checked = 0
    if a.customer_schema:
        cs, err = load(a.customer_schema, "customers")
        if err:
            rep.not_checked.append(f"Customer properties: the tool returned an error ({err}).")
        else:
            props = cs.get("properties") if isinstance(cs, dict) else cs
            by_level = {"high": [], "medium": [], "low": []}
            unused = []
            for p in props if isinstance(props, list) else []:
                if not isinstance(p, dict) or not p.get("property"):
                    continue
                props_checked += 1
                level = sensitivity(p["property"])
                if level:
                    by_level[level].append(p["property"])
                    if p.get("used") is False:
                        unused.append(p["property"])
            labels = {"high": "special-category or identity data", "medium": "direct identifiers or tracking IDs",
                      "low": "indirect identifiers"}
            for level in PRIORITIES:
                if by_level[level]:
                    rep.add(level, "personal customer property without retention", short(by_level[level]),
                            f"{len(by_level[level])} customer "
                            f"{'property looks' if len(by_level[level]) == 1 else 'properties look'} "
                            f"like {labels[level]}. Data Manager retention covers events only, so these stay on the "
                            "profile until it's anonymised or deleted.",
                            "Confirm each is needed and lawful to keep; drop what isn't used, and agree an "
                            "anonymisation or deletion routine for the rest.")
            if unused:
                rep.add("low", "personal property never filled", short(unused),
                        "Personal-looking customer properties that no customer has a value for.",
                        "Remove the definitions so nobody starts filling them by accident.")
    else:
        rep.not_checked.append("Personal customer properties: no --customer-schema file.")
    rep.not_checked.append("Scenarios' own wait and condition windows, exports, imports and API consumers: only the "
                           "definitions passed were read.")

    findings = sorted(rep.findings, key=lambda f: (PRIORITIES.index(f["priority"]), f["check"], f["subject"],
                                                   f["kind"] or "", f["name"] or ""))
    out = {"ok": True, "today": today.isoformat(),
           "default_retention": show(default),
           "counts": {p: sum(f["priority"] == p for f in findings) for p in PRIORITIES},
           "findings": findings, "events": rows,
           "windows": [{"kind": w["kind"], "name": w["name"], "event": w["event"], "mode": w["mode"],
                        "window": "all time" if w["days"] is INF else show(w["days"])}
                       for w in sorted(windows, key=lambda w: (w["event"], w["kind"], w["name"], w["mode"],
                                                               w["days"] or 0))],
           "customer_properties_checked": props_checked,
           "not_checked": sorted(set(rep.not_checked)),
           "disclaimer": "A data-management review, not legal advice. Check retention decisions with your data "
                         "protection lead or legal counsel."}
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
