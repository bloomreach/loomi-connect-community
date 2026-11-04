#!/usr/bin/env python3
"""Score the health of every Bloomreach Engagement project in a portfolio from list_projects_with_overview.

Usage:
  python3 portfolio_health.py --overview overview.json [--overview other_org.json]
         [--recent PROJECT=recent.json ...] [--scenarios PROJECT=active_scenarios.json ...]
         [--baseline previous_run.json] [--today 2026-11-04] [--table] [--out portfolio.json]

--overview   a saved list_projects_with_overview result (one per organisation; repeat for several).
--recent     deeper mode: a saved execute_analytics_eql result for
             "select count any event by any event type grouping top N in last 7 days", keyed by project ID or name.
--scenarios  deeper mode: a saved search_scenarios list with status="active", keyed by project ID or name.
--baseline   the JSON this script wrote on an earlier run (--out), to spot shrinking customer bases.

Prints JSON (or a Markdown table with --table): each project with its customers, events, event types, a health
score from 0 to 100, a band (green, amber, red) and flags with a priority and the skill to hand it to; portfolio
medians; the projects to check first in deeper mode and how many calls that takes; and what wasn't checked.
Rules are in references/rules.json. Never prints editor names, emails or account lists. Standard library only;
no network.
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from fractions import Fraction
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent.parent / "references" / "rules.json"
ORDER = {"high": 0, "medium": 1, "low": 2}
CONTEXT_ERROR = re.compile(r"\bproject\b|organi[sz]ation|\baccount\b|workspace|permission|\baccess\b|denied|"
                           r"forbidden|unauthori[sz]ed|\b40[13]\b|\b429\b|rate.?limit|too many", re.I)
URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.I)


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


def redact(text):
    """Error text that's safe to repeat: URLs removed, and cut short."""
    return URL.sub("[url]", str(text or "no error text"))[:200]


def load_rules():
    try:
        return json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        fail(f"can't read references/rules.json ({e}).")


def load(path):
    """A saved tool result with the {"result": ...} wrapper removed. A tool error stops the run."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            err = redact(d.get("error"))
            if CONTEXT_ERROR.search(err):
                fail(f"{path}: Loomi Connect returned an error about the project, organisation or access ({err}). "
                     "Leave this file out and report the project as not checked; don't treat it as 'nothing found'.")
            fail(f"{path}: the tool returned an error ({err}). This check couldn't run.")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    return data


def pairs(values, what):
    """NAME=FILE arguments, split on the first '='."""
    out = []
    for v in values or []:
        if "=" not in v:
            fail(f"{what} needs PROJECT=FILE, got {v!r}.")
        key, path = v.split("=", 1)
        if not key.strip() or not path.strip():
            fail(f"{what} needs PROJECT=FILE, got {v!r}.")
        out.append((key.strip(), path.strip()))
    return out


def count(v):
    """A whole number from a tool value, or None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v == v and v not in (float("inf"), float("-inf")) else None
    if isinstance(v, str) and re.fullmatch(r"\s*\d[\d,]*\s*", v):
        return int(v.replace(",", "").strip())
    return None


def median(values):
    vals = sorted(values)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def words(text):
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def looks_test(rec, rules):
    cat = str(rec.get("category") or "").strip().lower()
    if cat and cat in {c.lower() for c in rules["sandbox_categories"]}:
        return f"category '{cat}'"
    test_words = {w.lower() for w in rules["test_name_words"]}
    for field in ("name", "url_slug"):
        hit = sorted(words(rec.get(field)) & test_words)
        if hit:
            return f"'{hit[0]}' in the project {'name' if field == 'name' else 'URL slug'}"
    if re.search(r"\bcopy of\b", str(rec.get("name") or ""), re.I):
        return "'copy of' in the project name"
    return None


def shown(x):
    """A Fraction for display: whole numbers as int, others to 2 decimal places."""
    if x is None:
        return None
    if isinstance(x, Fraction) and x.denominator != 1:
        return round(float(x), 2)
    return int(x)


def eql_counts(result):
    data = result.get("data") if isinstance(result, dict) else None
    data = data if isinstance(data, dict) else {}
    out = {}
    for row in data.get("rows") or []:
        if not isinstance(row, dict):
            continue
        header = (row.get("headers") or [{}])[0] or {}
        if header.get("type") not in (None, "single"):
            continue
        values = row.get("values") or [0]
        out[str(header.get("value"))] = count(values[0]) or 0
    return out, data


def scenario_records(result):
    data = result.get("data") if isinstance(result, dict) else result
    return [r for r in (data or []) if isinstance(r, dict)]


def parse_today(text):
    if not text:
        return datetime.now(timezone.utc).date()
    try:
        return date.fromisoformat(text)
    except ValueError:
        fail(f"--today must be YYYY-MM-DD, got {text!r}.")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rules = load_rules()
    ap = argparse.ArgumentParser(description="Health-score every Engagement project in a portfolio.")
    ap.add_argument("--overview", action="append", required=True,
                    help="a saved list_projects_with_overview result; repeat for several organisations")
    ap.add_argument("--recent", action="append", default=[],
                    help="PROJECT=FILE: saved EQL event counts by event type for the last 7 days (deeper mode)")
    ap.add_argument("--scenarios", action="append", default=[],
                    help="PROJECT=FILE: saved search_scenarios list with status=active (deeper mode)")
    ap.add_argument("--baseline", help="the JSON this script wrote on an earlier run, to compare customer counts")
    ap.add_argument("--recent-top", type=int, default=rules["recent_top_n"],
                    help="the N used in 'grouping top N' in the recent query (default from rules.json)")
    ap.add_argument("--min-customers", type=int, default=rules["min_customers"],
                    help="flag projects with fewer customers than this (default from rules.json)")
    ap.add_argument("--max-deep", type=int, default=rules["max_deep_projects"],
                    help="most projects to suggest for deeper mode (default from rules.json)")
    ap.add_argument("--today", help="today's date as YYYY-MM-DD (default: today in UTC)")
    ap.add_argument("--table", action="store_true", help="print a Markdown table instead of JSON")
    ap.add_argument("--out", help="also write the JSON to this file in your working folder")
    args = ap.parse_args()
    today = parse_today(args.today)
    flag_rules = rules["flags"]

    # 1. Projects from every overview file, de-duplicated by ID.
    projects = {}
    for path in args.overview:
        data = load(path)
        recs = data.get("data") if isinstance(data, dict) else data
        if not isinstance(recs, list):
            fail(f"{path}: expected a list_projects_with_overview result with a list of projects.")
        for rec in recs:
            if isinstance(rec, dict) and rec.get("project_id"):
                projects.setdefault(str(rec["project_id"]), rec)
    if not projects:
        fail("no projects found in the overview files.")

    by_key = {}
    for pid, rec in projects.items():
        by_key[pid] = pid
        by_key.setdefault(str(rec.get("name") or "").strip().lower(), pid)

    def resolve(key, what):
        pid = by_key.get(key) or by_key.get(key.lower())
        if not pid:
            fail(f"{what}: no project with ID or name {key!r} in the overview files.")
        return pid

    recent = {resolve(k, "--recent"): load(p) for k, p in pairs(args.recent, "--recent")}
    scenarios = {resolve(k, "--scenarios"): load(p) for k, p in pairs(args.scenarios, "--scenarios")}

    baseline, baseline_date = {}, None
    if args.baseline:
        b = load(args.baseline)
        if not isinstance(b, dict) or not isinstance(b.get("projects"), list):
            fail(f"{args.baseline}: expected the JSON this script wrote earlier (with --out).")
        baseline_date = b.get("today")
        for p in b["projects"]:
            if isinstance(p, dict) and p.get("project_id"):
                baseline[str(p["project_id"])] = p

    # 2. Per-project facts.
    rows = []
    for pid, rec in projects.items():
        ov = rec.get("overview") if isinstance(rec.get("overview"), dict) else None
        types = ov.get("event_types_overview") if ov and isinstance(ov.get("event_types_overview"), dict) else None
        type_counts = {}
        for name, v in (types or {}).items():
            c = count(v.get("event_count") if isinstance(v, dict) else v)
            type_counts[str(name)] = c or 0
        customers = count(ov.get("total_customers")) if ov else None
        events = count(ov.get("events")) if ov else None
        oldest = ov.get("oldest_timestamp") if ov else None
        oldest_day = None
        if isinstance(oldest, (int, float)) and not isinstance(oldest, bool) and oldest > 0:
            oldest_day = datetime.fromtimestamp(oldest / 1000 if oldest > 1e11 else oldest, timezone.utc).date()
        epc = Fraction(events, customers) if events is not None and customers else None
        rows.append({
            "project_id": pid,
            "name": str(rec.get("name") or pid),
            "workspace": rec.get("workspace_name"),
            "category": rec.get("category"),
            "customers": customers,
            "events": events,
            "event_types": len(type_counts) if types is not None else None,
            "_epc": epc,
            "_types": type_counts if types is not None else None,
            "_overview_ok": ov is not None and not rec.get("overview_error"),
            "_overview_error": rec.get("overview_error"),
            "oldest_event": oldest_day.isoformat() if oldest_day else None,
            "test_like": looks_test(rec, rules),
            "flags": [],
            "checked": {"recent_events": pid in recent, "live_scenarios": pid in scenarios,
                        "baseline": pid in baseline},
        })

    def flag(row, code, detail):
        r = flag_rules[code]
        row["flags"].append({"code": code, "priority": r["priority"], "detail": detail, "handoff": r["handoff"]})

    # 3. Portfolio medians over comparable projects (not test-like, with events).
    comparable = [r for r in rows if r["_overview_ok"] and not r["test_like"] and r["events"] and r["customers"]]
    use_median = len(comparable) >= rules["min_projects_for_median"]
    med_customers = median([Fraction(r["customers"]) for r in comparable]) if use_median else None
    med_epc = median([r["_epc"] for r in comparable]) if use_median else None
    low = Fraction(str(rules["outlier_low_ratio"]))
    high = Fraction(str(rules["outlier_high_ratio"]))
    shrink = Fraction(str(rules["shrink_ratio"]))
    system = {s.lower() for s in rules["system_event_types"]}

    for row in rows:
        pid = row["project_id"]
        if row["test_like"]:
            flag(row, "test_or_sandbox", f"Looks like a test, sandbox or demo project ({row['test_like']}).")
        if not row["_overview_ok"]:
            err = row["_overview_error"]
            flag(row, "overview_unavailable", "The overview couldn't be read for this project"
                 + (f" ({redact(err)})." if err else "."))
            continue
        if row["events"] is None:
            flag(row, "events_unknown", "The overview has no readable event count, so event checks were skipped.")
        elif row["events"] == 0:
            flag(row, "no_events", "No events stored at all: tracking was never set up, or the data was deleted.")
        else:
            if row["customers"] is not None and row["customers"] < args.min_customers:
                flag(row, "small_customer_base", f"{row['customers']:,} customers (below {args.min_customers:,}).")
            if row["_types"] is not None:
                if row["event_types"] < rules["min_event_types"]:
                    flag(row, "few_event_types", f"Only {row['event_types']} event types tracked.")
                if not row["_types"].get("campaign"):
                    flag(row, "no_campaign_events", "No campaign events stored: this project has never recorded "
                         "an email, SMS, push or other campaign send.")
            if use_median and not row["test_like"]:
                parts = []
                if row["customers"] and row["customers"] < low * med_customers:
                    parts.append(f"customers {row['customers']:,} vs portfolio median {shown(med_customers):,}")
                if row["_epc"] is not None and med_epc and row["_epc"] < low * med_epc:
                    parts.append(f"events per customer {shown(row['_epc'])} vs median {shown(med_epc)}")
                if parts:
                    flag(row, "outlier_low", "Well below the portfolio: " + "; ".join(parts) + ".")
                if row["_epc"] is not None and med_epc and row["_epc"] > high * med_epc:
                    flag(row, "outlier_high", f"Events per customer {shown(row['_epc'])} vs median {shown(med_epc)}: "
                         "check for duplicate or bot tracking.")

        # Baseline comparison.
        b = baseline.get(pid)
        if b:
            bc, be = count(b.get("customers")), count(b.get("events"))
            since = f" since {baseline_date}" if baseline_date else " since the baseline"
            if bc and row["customers"] is not None and Fraction(bc - row["customers"], bc) > shrink:
                flag(row, "shrinking_customers", f"Customers fell from {bc:,} to {row['customers']:,}{since}.")
            if be and row["events"] is not None and row["events"] < be:
                flag(row, "fewer_events", f"Stored events fell from {be:,} to {row['events']:,}{since}: "
                     "data retention or deletion.")

        # Deeper mode.
        if pid in recent:
            counts, data = eql_counts(recent[pid])
            total = sum(counts.values())
            row["recent_events_7d"] = total
            if total == 0:
                flag(row, "no_recent_events", "No events at all in the last 7 days: tracking has stopped.")
            elif row["_types"]:
                full = len(data.get("rows") or []) >= args.recent_top
                busy = sorted(((c, n) for n, c in row["_types"].items() if n.lower() not in system and c > 0),
                              key=lambda t: (-t[0], t[1]))[:rules["busy_event_types"]]
                silent = sorted(n for _, n in busy if not counts.get(n))
                if silent and not full:
                    flag(row, "busy_types_silent", "Usually busy event types with no events in the last 7 days: "
                         + ", ".join(silent) + ".")
        if pid in scenarios:
            recs = [r for r in scenario_records(scenarios[pid])
                    if str(r.get("status") or "").lower() == "active" and not r.get("archived")]
            n = len(recs)
            row["live_scenarios"] = f"{n}+" if n >= rules["max_scenarios_page"] else n
            if n == 0:
                flag(row, "no_live_scenarios", "No active scenarios: no automated journeys are running.")

        row["flags"].sort(key=lambda f: (ORDER[f["priority"]], f["code"]))

    # 4. Scores and bands.
    for row in rows:
        if not row["_overview_ok"]:
            row["score"], row["band"] = None, "unknown"
            continue
        score = max(0, 100 - sum(flag_rules[f["code"]]["deduct"] for f in row["flags"]))
        row["score"] = score
        row["band"] = ("green" if score >= rules["score_green"] else
                       "amber" if score >= rules["score_amber"] else "red")
        row["events_per_customer"] = shown(row["_epc"])

    rows.sort(key=lambda r: (r["score"] is not None, r["score"] if r["score"] is not None else 0,
                             r["name"].lower(), r["project_id"]))

    # 5. Deeper-mode candidates: lowest scores first, comparable projects before test-like ones.
    unchecked = [r for r in rows if r["_overview_ok"] and r["events"]
                 and not (r["checked"]["recent_events"] and r["checked"]["live_scenarios"])]
    unchecked.sort(key=lambda r: (bool(r["test_like"]), r["score"], r["name"].lower(), r["project_id"]))
    candidates = unchecked[:max(0, args.max_deep)]

    handoffs = {}
    for row in rows:
        for f in row["flags"]:
            if f["code"] == "test_or_sandbox":
                continue
            handoffs.setdefault(f["handoff"], {}).setdefault(row["name"], set()).add(f["code"])
    handoff_list = [{"skill": skill, "projects": [{"name": n, "flags": sorted(c)} for n, c in sorted(ps.items())]}
                    for skill, ps in sorted(handoffs.items())]

    not_checked = []
    if not any(r["checked"]["recent_events"] for r in rows):
        not_checked.append("Recent activity: the overview has no last-event date, so 'tracking stopped' needs "
                           "deeper mode.")
    if not any(r["checked"]["live_scenarios"] for r in rows):
        not_checked.append("Live scenarios: the overview has no campaign or scenario counts, so 'no live "
                           "scenarios' needs deeper mode. 'No campaign events' is the overview-only proxy.")
    if not args.baseline:
        not_checked.append("Shrinking customer bases: needs a baseline from an earlier run (--baseline).")
    if not use_median:
        not_checked.append(f"Outliers: fewer than {rules['min_projects_for_median']} comparable projects, so no "
                           "portfolio median.")
    for r in rows:
        if not r["_overview_ok"]:
            not_checked.append(f"{r['name']}: overview unavailable.")

    bands = {b: sum(1 for r in rows if r["band"] == b) for b in ("green", "amber", "red", "unknown")}
    out_rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    result = {
        "ok": True,
        "today": today.isoformat(),
        "portfolio": {
            "projects": len(rows),
            "comparable_projects": len(comparable),
            "test_like_projects": sum(1 for r in rows if r["test_like"]),
            "customers_total": sum(r["customers"] or 0 for r in rows),
            "events_total": sum(r["events"] or 0 for r in rows),
            "median_customers": shown(med_customers),
            "median_events_per_customer": shown(med_epc),
            "bands": bands,
        },
        "projects": out_rows,
        "deeper_mode": {
            "checked": sorted(r["name"] for r in rows if r["checked"]["recent_events"] or r["checked"]["live_scenarios"]),
            "candidates": [{"project_id": r["project_id"], "name": r["name"], "score": r["score"]} for r in candidates],
            "calls_needed": len(candidates) * rules["deep_calls_per_project"],
            "more_not_listed": max(0, len(unchecked) - len(candidates)),
        },
        "handoffs": handoff_list,
        "not_checked": not_checked,
    }
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"can't write {args.out} ({e}).")
    if args.table:
        print(markdown(result))
    else:
        print(text)


def cell(v):
    if v is None:
        return "-"
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}"
    return str(v).replace("|", "/")


def markdown(result):
    lines = ["| Project | Workspace | Customers | Events | Event types | Events/customer | Score | Band | Flags |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in result["projects"]:
        flags = ", ".join(f["code"] for f in r["flags"]) or "none"
        lines.append("| " + " | ".join(cell(x) for x in (
            r["name"], r["workspace"], r["customers"], r["events"], r["event_types"],
            r.get("events_per_customer"), r["score"], r["band"], flags)) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
