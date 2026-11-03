#!/usr/bin/env python3
"""Audit saved Bloomreach Engagement on-site experience responses.

Standard library only. No network access. It reads JSON responses the
assistant has already saved from search_banners, search_in_app_messages,
search_surveys or search_experiments (list or detail mode) and prints audit
findings. It never prints variant HTML, scripts, styles or parameters.

Usage:
    python3 audit_experiences.py [--now UNIX_TS] [--stale-days 90] FILE [FILE ...]

Prefix a file with its kind if it isn't a banner response:
    python3 audit_experiences.py banners.json banner_1.json in_app:inapp.json survey:surveys.json

Kinds: banner (default), in_app, survey, experiment.
"""
import json
import re
import sys
import time
from itertools import combinations

KINDS = {"banner", "in_app", "survey", "experiment"}
MARKERS = re.compile(
    r"\b(draft|test|testing|copy|old|backup|dev|poc|qa|sandbox|do not use|temp|tmp)\b", re.I)
ARCHIVED_LABEL = re.compile(r"\barchived\b", re.I)
PREFIX = re.compile(r"^\s*(\[[^\]]*\]\s*)+")
POPUP_TYPES = re.compile(r"pop|overlay|slide|modal|bar|notification", re.I)


def unwrap(obj, path):
    """Return a list of records from a list or detail response."""
    for o in (obj, obj.get("result") if isinstance(obj, dict) else None):
        if isinstance(o, dict) and o.get("success") is False:
            sys.exit(f"{path}: Loomi Connect returned an error: {o.get('error') or 'no error text'}. "
                     "This check couldn't run; don't treat it as 'nothing found'.")
    if isinstance(obj, dict) and "result" in obj:
        obj = obj["result"]
    if isinstance(obj, dict) and "data" in obj:
        obj = obj["data"]
    if isinstance(obj, dict):
        return [obj]
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    return []


def base_name(name):
    n = PREFIX.sub("", name or "")
    n = MARKERS.sub("", n)
    n = re.sub(r"\b(v\d+|new)\b", "", n, flags=re.I)
    return re.sub(r"[^a-z0-9]+", " ", n.lower()).strip()


def page_rules(rec):
    trig = rec.get("trigger") or {}
    inc = trig.get("include_pages")
    if inc is None:
        return None
    rules = []
    for r in inc:
        if r.get("type") == "any":
            rules.append(("any", ""))
        else:
            rules.append((r.get("type", "?"), str(r.get("url", ""))))
    return rules


def pages_overlap(a, b):
    if a is None or b is None:
        return "unknown"
    for ta, ua in a:
        for tb, ub in b:
            if ta == "any" or tb == "any":
                return "yes"
            if ua and ub and (ua in ub or ub in ua):
                return "yes"
    return "no"


def audience_key(rec):
    cf = rec.get("customer_filter")
    if not cf or not (cf.get("filters") if isinstance(cf, dict) else cf):
        return None  # everyone
    return json.dumps(cf, sort_keys=True)


def schedule(rec, now):
    df = rec.get("date_filter")
    if not isinstance(df, dict) or not df.get("enabled"):
        return "none", None
    to = df.get("to_date")
    try:
        to = float(to) if to is not None else None
    except (TypeError, ValueError):
        to = None
    if to and to > 1e11:  # milliseconds
        to = to / 1000
    if to is None:
        return "open-ended", None
    return ("ended" if to < now else "scheduled"), to


def variant_summary(rec):
    vs = rec.get("variants")
    if not isinstance(vs, list):
        return None
    out = []
    for v in vs:
        out.append({
            "name": v.get("name"),
            "enabled": v.get("enabled", True),
            "percentage": v.get("percentage"),
            "type": v.get("type"),
            "embedded": v.get("is_embedded"),
        })
    return out


def is_popup(rec):
    for v in variant_summary(rec) or []:
        if v["embedded"]:
            continue
        if v["type"] and POPUP_TYPES.search(str(v["type"])):
            return True
    return False


def days(ts, now):
    try:
        return int((now - float(ts)) / 86400)
    except (TypeError, ValueError):
        return None


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    now = time.time()
    stale = 90
    files = []
    args = argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        return 0
    i = 0
    while i < len(args):
        if args[i] == "--now":
            now = float(args[i + 1]); i += 2; continue
        if args[i] == "--stale-days":
            stale = int(args[i + 1]); i += 2; continue
        files.append(args[i]); i += 1
    if not files:
        print(__doc__)
        return 2

    recs = {}
    for f in files:
        kind, path = "banner", f
        if ":" in f and f.split(":", 1)[0] in KINDS:
            kind, path = f.split(":", 1)
        with open(path, encoding="utf-8") as fh:
            for r in unwrap(json.load(fh), path):
                rid = r.get("_id") or r.get("id")
                if not rid:
                    continue
                key = (kind, str(rid))
                merged = recs.get(key, {})
                merged.update(r)
                merged["_kind"] = kind
                recs[key] = merged

    items = list(recs.values())
    live = [r for r in items if not r.get("archived")]
    active = [r for r in live if r.get("status") == "active"]

    print("## Inventory")
    for kind in sorted({r["_kind"] for r in items}):
        k = [r for r in items if r["_kind"] == kind]
        print(f"- {kind}: {sum(r.get('status') == 'active' and not r.get('archived') for r in k)} active, "
              f"{sum(r.get('status') != 'active' and not r.get('archived') for r in k)} not active, "
              f"{sum(bool(r.get('archived')) for r in k)} archived")
    no_detail = [r for r in active if "variants" not in r]
    if no_detail:
        print(f"- {len(no_detail)} active item(s) have no detail loaded; schedule, overlap and "
              "testing checks are skipped for them: " + "; ".join(r.get("name", "?").strip() for r in no_detail))

    findings = {"Action": [], "Test": [], "Review": [], "Cleanup": [], "Info": []}

    for r in active:
        name = (r.get("name") or "?").strip()
        if "variants" in r:
            state, to = schedule(r, now)
            if state == "ended":
                findings["Action"].append(f"{name}: active but its end date passed {days(to, now)} days ago")
            elif state in ("none", "open-ended"):
                findings["Review"].append(f"{name}: active with no end date (fine if always-on; add one if it's a promotion)")
            vs = [v for v in variant_summary(r) or [] if v["enabled"]]
            if len(vs) == 1 and (vs[0]["percentage"] in (None, 100)):
                if MARKERS.search(name) or re.search(r"split|control|holdout|a/?b", name, re.I):
                    findings["Info"].append(f"{name}: one variant, but the name suggests a test; it may split in code")
                else:
                    findings["Test"].append(f"{name}: one variant at 100%, never A/B tested")
            elif len(vs) > 1 and (days(r.get("edited"), now) or 0) >= 60:
                findings["Review"].append(f"{name}: {len(vs)} variants still splitting traffic after 60+ days; pick a winner")
            if r.get("customer_filter") in (None, {}):
                findings["Info"].append(f"{name}: shown to everyone (no customer filter)")
        if MARKERS.search(name):
            findings["Action"].append(f"{name}: active, but the name says it's a test, draft or old copy")
        age = days(r.get("edited"), now)
        if age is not None and age > 365:
            findings["Review"].append(f"{name}: active and not edited for {age} days; check it's still current")

    detailed = [r for r in active if "variants" in r]
    for a, b in combinations(detailed, 2):
        if a["_kind"] != b["_kind"]:
            continue
        p = pages_overlap(page_rules(a), page_rules(b))
        if p == "no":
            continue
        ka, kb = audience_key(a), audience_key(b)
        aud = "yes" if (ka is None or kb is None or ka == kb) else "possible"
        pair = f"{a.get('name', '?').strip()} + {b.get('name', '?').strip()}"
        detail = f"pages overlap: {p}; audiences overlap: {aud}"
        if p == "yes" and aud == "yes" and is_popup(a) and is_popup(b):
            findings["Action"].append(f"{pair}: two pop-up style experiences on the same pages and audience ({detail})")
        else:
            findings["Review"].append(f"{pair}: {detail}")

    stale_items, marked, labelled = [], [], []
    groups = {}
    for r in live:
        name = (r.get("name") or "?").strip()
        groups.setdefault((r["_kind"], base_name(name)), []).append(name)
        if r.get("status") == "active":
            continue
        age = days(r.get("edited"), now)
        if ARCHIVED_LABEL.search(name):
            labelled.append(name)
        elif MARKERS.search(name):
            marked.append(name)
        elif age is not None and age > stale:
            stale_items.append(name)
    if labelled:
        findings["Cleanup"].append(f"{len(labelled)} named as archived but not archived: " + "; ".join(labelled[:10]))
    if marked:
        findings["Cleanup"].append(f"{len(marked)} inactive drafts, tests or old copies: " + "; ".join(marked[:10])
                                   + (" ..." if len(marked) > 10 else ""))
    if stale_items:
        findings["Cleanup"].append(f"{len(stale_items)} other inactive items not edited for {stale}+ days"
                                   + (": " + "; ".join(stale_items[:10]) if len(stale_items) <= 10 else
                                      " (too many to list; archive in bulk after checking dependencies)"))
    dups = [v for (k, b), v in groups.items() if b and len(v) > 1]
    if dups:
        findings["Review"].append(f"{len(dups)} groups of near-duplicate names, e.g. " +
                                  " | ".join(" / ".join(v[:3]) for v in dups[:3]))

    for sev in ("Action", "Test", "Review", "Cleanup", "Info"):
        if findings[sev]:
            print(f"\n## {sev}")
            for f in findings[sev]:
                print(f"- {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
