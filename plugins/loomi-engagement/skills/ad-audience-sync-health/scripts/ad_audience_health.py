#!/usr/bin/env python3
"""Check audiences sent to ad platforms, external segments and autosegments in Bloomreach Engagement, from saved tool results.

Usage:
  python3 ad_audience_health.py [--external FILE] [--segmentations FILE] [--segmentation-detail FILE ...]
      [--autosegments FILE] [--autosegment-detail FILE ...] [--integrations FILE] [--scenario FILE ...]
      [--consent-settings FILE] [--size KEY=COUNT_OR_FILE ...] [--last-sync KEY=DATE_OR_TIMESTAMP ...]
      [--denied KIND ...] [--today YYYY-MM-DD] [--out report.json]

  --external             the saved search_external_segments response
  --segmentations        the saved search_segmentations list (names, archived flags, used_by)
  --segmentation-detail  a saved search_segmentations detail, to see whether it filters on consent
  --autosegments         the saved search_autosegments list
  --autosegment-detail   a saved search_autosegments detail (used_by, archived, job error)
  --integrations         the saved search_integrations list, to recognise ad-platform destinations
  --scenario             a saved search_scenarios detail (no designs needed), to find ad-audience steps
  --consent-settings     the saved get_consent_settings response
  --size KEY=...         an audience's size: a number, or a saved aggregate EQL count (a .json path;
                         only each row's first value, the count column, is added up)
  --last-sync KEY=...    an audience's last sync: YYYY-MM-DD, an ISO time or Unix seconds
  --denied KIND          a tool that returned HTTP 403 (external, autosegments, segmentations, scenarios,
                         integrations, consent)
KEY is an external segment's ID or name, or <scenario id>:<node id> for an ad-audience step. NAME=VALUE
inputs are split on the first "=".

Prints JSON (or writes it to --out): each audience (external segment or ad-audience step) with its
destination, source segmentations, size, last sync and findings; each autosegment with its run
status, use and findings; duplicates; and a summary. Priorities are high, medium or low. Thresholds
come from references/rules.json; platform minimum sizes there are rules of thumb. It works on
definitions and counts only and never sees a customer.

Standard library only; no network access. Writes nothing to Bloomreach.
"""
import argparse
import datetime
import json
import math
import re
import sys
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent.parent / "references" / "rules.json"
MISSING = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}
PRIORITY = {"high": 0, "medium": 1, "low": 2}
CONTEXT_WORDS = re.compile(r"project|organi[sz]ation|account|access|denied|forbidden|unauthori[sz]ed|\b40[13]\b|\b429\b|too many requests", re.I)
URL = re.compile(r"(?i)\b(?:https?|wss?|ftp)://[^\s'\"<>]+")
DENIABLE = ("external", "autosegments", "segmentations", "scenarios", "integrations", "consent")
DAY = 86400


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def redact(text):
    return URL.sub("[url]", str(text))


def load_rules():
    try:
        return json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except OSError as e:
        fail(f"can't read references/rules.json ({e.strerror or e}).")
    except json.JSONDecodeError as e:
        fail(f"references/rules.json is not valid JSON ({e}).")


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


def load(path, allow_missing_item=False):
    """Read a saved tool result. A context error stops the run; a not-found on the item returns None."""
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
        err = redact(data.get("error") or "no error text")
        if allow_missing_item and not CONTEXT_WORDS.search(err) and re.search(r"not found|does not exist|no such", err, re.I):
            return None
        fail(f"{path}: Loomi Connect returned an error: {err}. Sort out the project or access before going on; "
             "don't treat it as 'nothing found'.")
    if isinstance(data, dict) and "success" in data and "data" in data:
        data = data["data"]
    return data


def records(data):
    if isinstance(data, dict):
        for key in ("data", "items", "results", "segments", "segmentations", "autosegments"):
            if isinstance(data.get(key), list):
                return [r for r in data[key] if isinstance(r, dict)]
        return [data]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def rid(r):
    for k in ("_id", "id", "segment_id", "external_segment_id"):
        if r.get(k) not in (None, ""):
            return str(r[k])
    return None


def pair(text):
    name, sep, value = text.partition("=")
    if not sep or not name.strip() or not value.strip():
        raise argparse.ArgumentTypeError(f"expected NAME=VALUE, got {text!r}")
    return name.strip(), value.strip()


def as_ts(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"\s*\d+(\.\d+)?\s*", v)):
        x = number(v)
        return x / 1000 if x is not None and x > 1e11 else x
    if isinstance(v, str) and v.strip():
        try:
            dt = datetime.datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    return None


def ts_day(ts):
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).date().isoformat() if ts is not None else None


def count_value(value, label):
    """A count from a plain number or a saved aggregate EQL result (a path ending .json). Only each
    row's first value (the count column) is added up, so extra metric columns aren't counted."""
    if value.lower().endswith(".json"):
        data = load(value)
        rows = data.get("rows") if isinstance(data, dict) else None
        if rows is None and isinstance(data, dict) and isinstance(data.get("data"), dict):
            rows = data["data"].get("rows")
        if not isinstance(rows, list):
            fail(f"{label}: no EQL rows found in {value}; save the execute_analytics_eql result or give a number.")
        total = 0
        for r in rows:
            vals = r.get("values") if isinstance(r, dict) else None
            if vals:
                x = number(vals[0])
                total += int(x) if x is not None and x > 0 else 0
        return total
    x = number(value)
    if x is None or x < 0 or not re.fullmatch(r"\s*[\d,]+(\.\d+)?\s*", value):
        fail(f"{label}: {value!r} is neither a saved EQL result (.json) nor a count.")
    return int(x)


def norm(text):
    return re.sub(r"[_\-\s]+", " ", str(text or "").lower())


def words_in(text, words):
    """Words (or phrases) that start a word in text; "_" and "-" count as spaces, so "ads" matches
    "facebook-ads" but not "uploads"."""
    t = norm(text)
    return sorted(w for w in words if re.search(r"(?<![a-z0-9])" + re.escape(norm(w)), t))


def walk(x):
    stack = [x]
    while stack:
        y = stack.pop()
        if isinstance(y, dict):
            yield y
            stack.extend(y.values())
        elif isinstance(y, list):
            stack.extend(y)


def consent_refs(obj):
    """Consent category names or IDs used in conditions anywhere inside obj."""
    out = set()
    for d in walk(obj):
        if str(d.get("type") or "").lower() == "consent":
            c = d.get("category") or d.get("category_id") or d.get("id")
            out.add(str(c) if c is not None else "")
    return out


def segmentation_refs(obj):
    out = set()
    for d in walk(obj):
        if str(d.get("type") or "").lower() == "segmentation" and d.get("id"):
            out.add(str(d["id"]))
        if d.get("segmentation_id"):
            out.add(str(d["segmentation_id"]))
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rules = load_rules()
    ap = argparse.ArgumentParser(description="Ad audience, external segment and autosegment health from saved Loomi Connect results.")
    ap.add_argument("--external", help="saved search_external_segments response")
    ap.add_argument("--segmentations", help="saved search_segmentations list")
    ap.add_argument("--segmentation-detail", action="append", default=[], help="saved search_segmentations detail (repeatable)")
    ap.add_argument("--autosegments", help="saved search_autosegments list")
    ap.add_argument("--autosegment-detail", action="append", default=[], help="saved search_autosegments detail (repeatable)")
    ap.add_argument("--integrations", help="saved search_integrations list")
    ap.add_argument("--scenario", action="append", default=[], help="saved search_scenarios detail (repeatable)")
    ap.add_argument("--consent-settings", help="saved get_consent_settings response")
    ap.add_argument("--size", action="append", default=[], type=pair, help="KEY=COUNT_OR_FILE: an audience's size")
    ap.add_argument("--last-sync", action="append", default=[], type=pair, help="KEY=DATE: an audience's last sync")
    ap.add_argument("--denied", action="append", default=[], choices=DENIABLE, help="a tool that returned HTTP 403")
    ap.add_argument("--today", help="today's date, YYYY-MM-DD (default: the system date, UTC)")
    ap.add_argument("--stale-sync-days", type=float, default=rules["stale_sync_days"], help="days before a sync is stale (rules: stale_sync_days)")
    ap.add_argument("--stale-autosegment-days", type=float, default=rules["stale_autosegment_days"], help="days before an autosegment run is stale (rules: stale_autosegment_days)")
    ap.add_argument("--out", help="write the JSON report here instead of printing it")
    a = ap.parse_args()
    if not (a.external or a.autosegments or a.scenario):
        fail("give at least one of --external, --autosegments or --scenario.")
    try:
        today = datetime.date.fromisoformat(a.today) if a.today else datetime.datetime.now(datetime.timezone.utc).date()
    except ValueError:
        fail(f"--today: {a.today!r} isn't a date (YYYY-MM-DD).")
    now = datetime.datetime(today.year, today.month, today.day, tzinfo=datetime.timezone.utc).timestamp()
    live_statuses = {s.lower() for s in rules["live_statuses"]}
    failing = re.compile(r"\b(" + "|".join(re.escape(s) for s in rules["failing_statuses"]) + r")\b", re.I)

    # Segmentations
    segs = {}
    if a.segmentations:
        for r in records(load(a.segmentations)):
            if rid(r):
                segs[rid(r)] = {"id": rid(r), "name": r.get("name"), "archived": bool(r.get("archived")), "consent": None}
    for path in a.segmentation_detail:
        d = load(path, allow_missing_item=True)
        for r in records(d) if d is not None else []:
            if rid(r):
                s = segs.setdefault(rid(r), {"id": rid(r), "name": r.get("name"), "archived": bool(r.get("archived"))})
                s["consent"] = sorted(consent_refs(r))
    seg_by_name = {}
    for s in segs.values():
        seg_by_name.setdefault(str(s["name"] or "").strip().lower(), []).append(s["id"])

    # Consent categories
    categories, ad_categories = [], []
    if a.consent_settings:
        cs = load(a.consent_settings)
        for c in (cs.get("categories") if isinstance(cs, dict) else None) or []:
            if not isinstance(c, dict):
                continue
            names = [str(c.get("id") or "")] + [str((t or {}).get("name") or "") for t in (c.get("translations") or {}).values() if isinstance(t, dict)]
            if c.get("name"):
                names.append(str(c["name"]))
            categories.append(names)
            if any(words_in(n, rules["ad_consent_words"]) for n in names):
                ad_categories.append(names)
    uses_consent = bool(categories)
    ad_names = {n.lower() for names in ad_categories for n in names if n}

    def consent_ok(refs):
        refs = {r.lower() for r in refs if r}
        if not refs:
            return False
        return bool(refs & ad_names) if ad_names else True

    # Integrations
    ads_integrations = {}
    if a.integrations:
        for r in records(load(a.integrations)):
            t = f"{r.get('type') or ''} {r.get('name') or ''}"
            if rid(r) and words_in(t, rules["ads_integration_words"]):
                ads_integrations[rid(r)] = {"type": r.get("type"), "name": r.get("name")}

    sizes = {k: count_value(v, "--size") for k, v in a.size}
    syncs = {}
    for k, v in a.last_sync:
        t = as_ts(v)
        if t is None:
            fail(f"--last-sync: {v!r} isn't a date, time or timestamp.")
        syncs[k] = t

    def pick(r, kind):
        for f in rules["external_fields"][kind]:
            if r.get(f) not in (None, ""):
                return r[f]
        return None

    def min_size(dest):
        d = (dest or "").lower()
        for word, n in sorted(rules["platform_min_sizes"].items()):
            if word in d:
                return n, word
        return rules["default_min_size"], None

    audiences = []

    # External segments
    if a.external:
        for r in records(load(a.external)):
            eid = rid(r)
            if not eid:
                continue
            name = r.get("name")
            dest = pick(r, "destination")
            status = pick(r, "status")
            last = pick(r, "last_sync")
            last = as_ts(last) if last is not None else None
            size = number(pick(r, "size"))
            seg_id = pick(r, "segmentation")
            for key in (eid, str(name or "")):
                if key in sizes:
                    size = sizes[key]
                if key in syncs:
                    last = syncs[key]
            linked, link_how = [], None
            if seg_id:
                linked, link_how = [str(seg_id)], "segmentation id"
            elif segs and name:
                linked, link_how = seg_by_name.get(str(name).strip().lower(), []), "name"
            audiences.append({"kind": "external_segment", "key": eid, "name": name, "destination": dest,
                              "status": status, "last_sync": last, "size": None if size is None else int(size),
                              "live": None, "sources": linked, "source_link": link_how, "consent": None,
                              "matched_by": None, "fields_returned": sorted(k for k in r if k not in ("_id", "id", "name"))})

    # Ad-audience steps in scenarios
    non_ad = set(rules["non_ad_node_types"])
    for path in a.scenario:
        d = load(path, allow_missing_item=True)
        if d is None:
            continue
        for sc in records(d):
            sid = rid(sc)
            nodes = {n.get("id"): n for n in sc.get("nodes") or [] if isinstance(n, dict)}
            incoming = {}
            for c in sc.get("connections") or []:
                try:
                    incoming.setdefault(c["destination"]["node_id"], []).append(c["source"]["node_id"])
                except (KeyError, TypeError):
                    continue
            live = (not sc.get("archived")) and str(sc.get("status") or "").lower() in live_statuses
            for nid, n in sorted(nodes.items(), key=lambda kv: str(kv[0])):
                ntype = str(n.get("type") or "")
                if ntype in non_ad:
                    continue
                text = json.dumps(n, sort_keys=True)
                integ = sorted(i for i in ads_integrations if i in text)
                kw = words_in(ntype, rules["ad_node_words"])
                if not integ and not kw:
                    continue
                if integ:
                    dest = ads_integrations[integ[0]]["type"] or ads_integrations[integ[0]]["name"]
                else:
                    dest = ntype
                # walk back to the trigger for the audience
                seen, stack, path_nodes = set(), [nid], []
                while stack:
                    x = stack.pop()
                    for src in incoming.get(x, []):
                        if src not in seen:
                            seen.add(src)
                            stack.append(src)
                            if src in nodes:
                                path_nodes.append(nodes[src])
                path_nodes.sort(key=lambda p: str(p.get("id")))
                srcs, crefs = set(), set()
                for p in path_nodes + [n]:
                    srcs |= segmentation_refs(p)
                    crefs |= consent_refs(p)
                for s in srcs:
                    if segs.get(s, {}).get("consent"):
                        crefs |= set(segs[s]["consent"])
                key = f"{sid}:{nid}"
                audiences.append({"kind": "ad_audience_step", "key": key, "name": f"{sc.get('name') or sid} / {n.get('name') or ntype}",
                                  "destination": dest, "status": sc.get("status"), "last_sync": syncs.get(key),
                                  "size": sizes.get(key), "live": live, "sources": sorted(srcs), "source_link": "scenario path",
                                  "consent": sorted(crefs), "has_path_filter": any(p.get("customer_filter") for p in path_nodes) or bool(srcs),
                                  "matched_by": "ads integration id" if integ else f"node type ({', '.join(kw)})",
                                  "fields_returned": None})

    # Checks per audience
    for au in audiences:
        f = []
        hi = "high" if au["live"] else "medium"
        if au["status"] is not None and failing.search(str(au["status"])) and au["kind"] == "external_segment":
            f.append(("high", "failing", f"Last sync status is '{au['status']}'."))
        if au["last_sync"] is not None:
            age = (now - au["last_sync"]) / DAY
            au["days_since_sync"] = round(age, 1)
            if age > a.stale_sync_days:
                f.append((hi, "stale", f"Last synced {round(age)} days ago ({ts_day(au['last_sync'])})."))
        else:
            au["days_since_sync"] = None
            f.append(("low", "sync_time_unknown", "No last sync time: the tool doesn't return one; get it from the platform or a --last-sync value."))
        if au["size"] is not None:
            floor, platform = min_size(au["destination"])
            au["min_size_rule_of_thumb"] = floor
            if au["size"] == 0:
                f.append((hi, "empty", "The audience is empty."))
            elif au["size"] < floor:
                f.append(("medium", "too_small", f"About {au['size']} customers, under the rule-of-thumb minimum of {floor} for "
                          f"{platform or 'an ad platform'}; matched users will be fewer still."))
        else:
            au["min_size_rule_of_thumb"] = None
        for s in au["sources"]:
            if segs and s not in segs:
                f.append(("high", "source_missing", f"Source segmentation {s} wasn't found."))
            elif s in segs and segs[s]["archived"]:
                f.append(("high", "source_archived", f"Source segmentation '{segs[s]['name']}' is archived."))
        if au["kind"] == "external_segment" and not au["sources"] and segs:
            f.append(("low", "no_linked_segmentation", "No segmentation with this name was found; check how it's used in campaigns."))
        if uses_consent:
            if au["kind"] == "external_segment":
                refs = set()
                for s in au["sources"]:
                    refs |= set(segs.get(s, {}).get("consent") or [])
                checked = any(segs.get(s, {}).get("consent") is not None for s in au["sources"])
                au["consent"] = sorted(refs) if checked else None
                if checked and not consent_ok(refs):
                    f.append(("medium", "no_ad_consent", "Its segmentation has no advertising consent condition."))
            elif not consent_ok(au["consent"] or []):
                f.append((hi, "no_ad_consent", "Nothing on the path to this step filters on advertising consent."))
        if au["kind"] == "ad_audience_step" and not au.get("has_path_filter"):
            f.append(("low", "no_audience_filter", "No condition or segment on the path: everyone the trigger reaches is sent."))
        au["findings"] = f

    # Duplicates: same destination and same source
    groups = {}
    for au in audiences:
        if au["destination"] and au["sources"]:
            groups.setdefault((str(au["destination"]).lower(), tuple(au["sources"])), []).append(au)
        elif au["destination"] and au["name"] and au["kind"] == "external_segment":
            groups.setdefault((str(au["destination"]).lower(), ("name:" + str(au["name"]).strip().lower(),)), []).append(au)
    duplicates = []
    for (dest, src), items in sorted(groups.items()):
        if len(items) > 1:
            keys = sorted(i["key"] for i in items)
            duplicates.append({"destination": dest, "source": list(src), "audiences": keys})
            for i in items:
                i["findings"].append(("medium", "duplicate", f"{len(items)} audiences send the same source to {dest}."))
    for au in audiences:
        au["findings"] = [{"priority": p, "kind": k, "detail": d} for p, k, d in sorted(au["findings"], key=lambda x: (PRIORITY[x[0]], x[1]))]
        if au["last_sync"] is not None:
            au["last_sync"] = ts_day(au["last_sync"])
        au.pop("has_path_filter", None)

    # Autosegments
    autos = {}
    if a.autosegments:
        for r in records(load(a.autosegments)):
            if rid(r):
                ji = r.get("job_info") or {}
                autos[rid(r)] = {"id": rid(r), "name": r.get("name"), "status": ji.get("status"), "last_run": as_ts(ji.get("last_run_at")),
                                 "error": bool(ji.get("error")), "used_by": None, "archived": bool(r.get("archived"))}
    for path in a.autosegment_detail:
        d = load(path, allow_missing_item=True)
        for r in records(d) if d is not None else []:
            if not rid(r):
                continue
            ji = r.get("job_info") or {}
            x = autos.setdefault(rid(r), {"id": rid(r), "name": r.get("name"), "status": None, "last_run": None, "error": False})
            x.update({"status": ji.get("status", x.get("status")), "last_run": as_ts(ji.get("last_run_at")) or x.get("last_run"),
                      "error": bool(ji.get("error")) or x.get("error", False), "archived": bool(r.get("archived")),
                      "used_by": sorted(str(u) for u in r.get("used_by") or [])})
    out_autos = []
    for x in sorted(autos.values(), key=lambda v: (str(v["name"] or "").lower(), v["id"])):
        f = []
        st = str(x["status"] or "").lower()
        if x.get("archived"):
            continue
        if st == "failed" or x["error"]:
            f.append(("medium", "failed", "Its last run failed."))
        elif st == "draft":
            f.append(("low", "never_run", "Still a draft: it has never produced segments."))
        age = (now - x["last_run"]) / DAY if x["last_run"] is not None else None
        if age is not None and age > a.stale_autosegment_days and st != "draft":
            f.append(("low" if x["used_by"] == [] else "medium", "stale", f"Last ran {round(age)} days ago ({ts_day(x['last_run'])})."))
        if x["used_by"] is None:
            f.append(("low", "use_not_checked", "Detail not loaded, so its use wasn't checked."))
        elif not x["used_by"]:
            f.append(("low", "unused", "Nothing references it (used_by is empty): review, then archive if nobody reads it."))
        out_autos.append({"id": x["id"], "name": x["name"], "status": x["status"], "last_run": ts_day(x["last_run"]),
                          "days_since_run": round(age, 1) if age is not None else None,
                          "used_by_count": None if x["used_by"] is None else len(x["used_by"]),
                          "findings": [{"priority": p, "kind": k, "detail": d} for p, k, d in sorted(f, key=lambda y: (PRIORITY[y[0]], y[1]))]})

    def worst(item):
        return min((PRIORITY[f["priority"]] for f in item["findings"]), default=3)

    audiences.sort(key=lambda x: (worst(x), str(x["name"] or "").lower(), x["key"]))
    out_autos.sort(key=lambda x: (worst(x), str(x["name"] or "").lower(), x["id"]))
    summary = {"audiences": len(audiences), "external_segments": sum(1 for x in audiences if x["kind"] == "external_segment"),
               "ad_audience_steps": sum(1 for x in audiences if x["kind"] == "ad_audience_step"),
               "ads_integrations": len(ads_integrations), "autosegments": len(out_autos), "duplicates": len(duplicates)}
    for p in PRIORITY:
        summary[p] = sum(1 for x in audiences + out_autos for f in x["findings"] if f["priority"] == p)
    result = {"ok": True, "today": today.isoformat(), "summary": summary,
              "ads_destinations": [{"id": k, **v} for k, v in sorted(ads_integrations.items())],
              "consent": {"uses_categories": uses_consent, "advertising_categories": sorted({n[0] for n in ad_categories})},
              "audiences": audiences, "duplicates": duplicates, "autosegments": out_autos,
              "not_checked": sorted(set(a.denied))}
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text + "\n")
        except OSError as e:
            fail(f"--out {a.out}: can't write the file ({e.strerror or e}).")
        print(json.dumps({"ok": True, "out": a.out, "summary": summary}))
    else:
        print(text)


if __name__ == "__main__":
    main()
