#!/usr/bin/env python3
"""Trend email deliverability by week from saved EQL results, and flag guard-rail breaches, drift and spikes.

Usage:
  python3 deliverability_trend.py --daily daily.json [--breakdown sender=sender.json]
         [--breakdown integration=integration.json] [--breakdown campaign=campaign.json] [--scenarios scenarios.json]
         [--breakdown new_audience=new.json] [--breakdown spike:2026-10-19=week.json]
         [--start 2026-08-05] [--end 2026-11-03] [--utc-offset 1] [--recent-weeks 4] [--min-weekly-sends 1000] [--out trend.json]

Inputs are saved execute_analytics_eql results (the whole tool result):
  --daily     the daily cross-tab: rows `event campaign timestamp ... format year month day`, columns
              `event campaign.status` (required). Day headers are Unix seconds at local midnight in the project's
              time zone, or YYYY-MM-DD text.
  --breakdown NAME=FILE (repeatable), each a cross-tab with the dimension in rows and status in columns,
              over the same window as --daily unless noted:
                sender        rows `campaign.sender`; addresses are reduced to their domain, never printed whole
                integration   rows `campaign.integration_name` (the sending integration)
                campaign      rows `campaign.campaign_id`; with --scenarios, each row is typed scenario or one-off
                new_audience  a status breakdown (single or cross-tab) of events from customers with no delivered
                              email before the window; 'established' is the window total minus it
                spike:<date>  rows `campaign.campaign_name` for the week starting <date> (a Monday)
  --scenarios a saved search_scenarios list: every id in it marks a campaign_id as a scenario.
  --start / --end (YYYY-MM-DD, end exclusive) the queried window, so partial weeks are marked; default: the days
              in --daily. Timestamp day headers are dated by counting days from --start (the first header is taken
              to be --start), or from --utc-offset when given; one of the two is required for them.

Rates (exact fractions, rounded only for display): delivery, hard and soft bounce of sends; complaint and
unsubscribe of delivered. Sends are enqueued if the data has any, else sent, else delivered + bounces + failed.
Weeks run Monday to Sunday. The last --recent-weeks are compared with the weeks before them (the baseline).
Thresholds, guard-rails and status names are in references/rules.json. Prints JSON (or writes --out) with weeks,
the baseline and recent rates, prioritised findings and the breakdowns. Standard library only; no network access.
"""
import argparse
import json
import math
import re
import sys
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
MISSING = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}
METRICS = ("delivery_rate", "hard_bounce_rate", "soft_bounce_rate", "complaint_rate", "unsubscribe_rate")
NUMERATOR = {"delivery_rate": "delivered", "hard_bounce_rate": "hard_bounce", "soft_bounce_rate": "soft_bounce",
             "complaint_rate": "complaint", "unsubscribe_rate": "unsubscribe"}
DENOMINATOR = {"delivery_rate": "sends", "hard_bounce_rate": "sends", "soft_bounce_rate": "sends",
               "complaint_rate": "delivered", "unsubscribe_rate": "delivered"}
COUNTED = ("enqueued", "sent", "delivered", "hard_bounce", "soft_bounce", "complaint", "unsubscribe", "failed",
           "opened", "clicked")
PRIORITY = {"high": 0, "medium": 1, "low": 2}
KIND = {"guardrail": 0, "drift": 1, "spike": 2, "breakdown": 3}
NOT_RECORDED = "(not recorded)"
OTHER = "(other)"


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


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


def count(v):
    x = number(v)
    return 0 if x is None or x < 0 else int(x)


def load(path):
    """The report body (rows and columns) of a saved execute_analytics_eql result."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {str(d.get('error') or 'no error text')[:200]} "
                 "This check couldn't run; don't treat it as 'nothing found'.")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    body = data.get("data") if isinstance(data, dict) else None
    if not isinstance(body, dict) or not isinstance(body.get("rows"), list):
        fail(f"{path}: no data.rows in the file. Pass the whole saved execute_analytics_eql result.")
    return body


def header(h):
    if not isinstance(h, dict):
        return None
    if h.get("type") == "other":
        return OTHER
    return h.get("value")


def canonical(status):
    return RULES["status_aliases"].get(str(status).strip().lower()) if status is not None else None


def add(counts, status, n):
    key = canonical(status)
    if key:
        counts[key] = counts.get(key, 0) + n


def table(path):
    """[(row header, {metric status: count})]. A breakdown by status alone comes back as one row with header None."""
    body = load(path)
    cols = [header(c[0]) if isinstance(c, list) and c else None for c in body.get("columns") or []]
    crosstab = any(c is not None for c in cols)
    out = {}
    for r in body["rows"]:
        if not isinstance(r, dict):
            continue
        heads = r.get("headers") or [None]
        values = r.get("values") or []
        if crosstab:
            key = header(heads[0])
            counts = out.setdefault(key, {})
            for status, v in zip(cols, values):
                add(counts, status, count(v))
        else:
            counts = out.setdefault(None, {})
            add(counts, header(heads[0]), count(values[0] if values else 0))
    return list(out.items())


def day_of(h, path):
    """A text day header (YYYY-MM-DD), or None for a numeric one (placed later by place_days)."""
    if isinstance(h, (int, float)) and not isinstance(h, bool):
        return None
    try:
        return date.fromisoformat(str(h)[:10])
    except ValueError:
        fail(f"{path}: a row header isn't a day ({h!r}). Use `by row event campaign timestamp ... format year "
             "month day` with status in columns.")


def place_days(stamps, start, utc_offset, path):
    """Days for numeric headers: Unix seconds at local midnight in the project's time zone.

    No rule on the timestamps alone works for every offset (UTC-12 to UTC+14 spans 26 hours), so the day comes
    from the project's UTC offset when given, and otherwise by counting whole days from the first header, which is
    taken to be --start. Rounding the day count absorbs 23- and 25-hour daylight-saving days."""
    if utc_offset is not None:
        return {h: datetime.fromtimestamp(int(h) + round(utc_offset * 3600), timezone.utc).date() for h in stamps}
    if start is None:
        fail(f"{path}: the day headers are timestamps, so --start (the first day of the queried window, which "
             "must have email) or --utc-offset (the project's offset from UTC in hours) is needed to date them.")
    first = min(stamps)
    return {h: start + timedelta(days=round((int(h) - int(first)) / 86400)) for h in stamps}


def total(rows):
    out = {}
    for c in rows:
        for k, v in c.items():
            out[k] = out.get(k, 0) + v
    return out


def basis_of(counts):
    if counts.get("enqueued"):
        return "enqueued"
    if counts.get("sent"):
        return "sent"
    return "derived"


def sends(c, basis):
    if basis == "derived":
        return c.get("delivered", 0) + c.get("hard_bounce", 0) + c.get("soft_bounce", 0) + c.get("failed", 0)
    return c.get(basis, 0)


def rates(c, basis):
    base = {"sends": sends(c, basis), "delivered": c.get("delivered", 0)}
    return {m: (Fraction(c.get(NUMERATOR[m], 0), base[DENOMINATOR[m]]) if base[DENOMINATOR[m]] else None)
            for m in METRICS}


def pct(r):
    return None if r is None else round(float(r * 100), 3)


def limit(metric, level):
    g = RULES["guardrails"][metric]
    key = (level + "_below") if metric == "delivery_rate" else level
    return Fraction(str(g[key])) / 100


def crossed(metric, r):
    """'limit', 'warn' or None for one rate against the guard-rails."""
    if r is None:
        return None
    for level in ("limit", "warn"):
        t = limit(metric, level)
        if (r < t) if metric == "delivery_rate" else (r >= t):
            return level
    return None


def median(xs):
    s = sorted(xs)
    if not s:
        return None
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def domain(sender):
    if sender is None:
        return NOT_RECORDED
    s = str(sender).strip().strip("<>").lower()
    if "@" in s:
        return s.rsplit("@", 1)[1].strip(" >") or NOT_RECORDED
    return s or NOT_RECORDED


def scenario_ids(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {str(d.get('error') or 'no error text')[:200]}")
    ids = set()

    def walk(o):
        if isinstance(o, dict):
            for k in ("id", "_id", "scenario_id"):
                if isinstance(o.get(k), str):
                    ids.add(o[k])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    return ids


def group_row(name, c, basis, min_sends):
    r = rates(c, basis)
    n = sends(c, basis)
    judged = n >= min_sends
    flags = {m: crossed(m, r[m]) for m in METRICS} if judged else {}
    return {"name": name, "sends": n, "delivered": c.get("delivered", 0),
            "hard_bounce": c.get("hard_bounce", 0), "soft_bounce": c.get("soft_bounce", 0),
            "complaint": c.get("complaint", 0), "unsubscribe": c.get("unsubscribe", 0),
            "rates_pct": {m: pct(r[m]) for m in METRICS}, "judged": judged,
            "flags": {m: v for m, v in sorted(flags.items()) if v}}


def problems(row):
    return row["hard_bounce"] + row["soft_bounce"] + row["complaint"] + row["unsubscribe"]


def analyse(daily_rows, breakdowns, scenarios, args):
    days = {}
    numeric = place_days([h for h, _ in daily_rows if day_of(h, args.daily) is None], args.start,
                         args.utc_offset, args.daily) if daily_rows else {}
    for h, c in daily_rows:
        d = numeric[h] if h in numeric else day_of(h, args.daily)
        days.setdefault(d, {})
        for k, v in c.items():
            days[d][k] = days[d].get(k, 0) + v
    if not days:
        fail(f"{args.daily}: no rows. The project sent no email in the window (or the filter matched nothing); "
             "say so rather than reporting a trend.")
    start = args.start or min(days)
    end = args.end or (max(days) + timedelta(days=1))
    window_total = total(days.values())
    basis = basis_of(window_total)

    weeks = {}
    for d, c in days.items():
        if start <= d < end:
            w = weeks.setdefault(d - timedelta(days=d.weekday()), {})
            for k, v in c.items():
                w[k] = w.get(k, 0) + v
    order = sorted(weeks)
    recent_set = set(order[-args.recent_weeks:]) if args.recent_weeks > 0 else set()
    week_rows = []
    for w in order:
        c = weeks[w]
        r = rates(c, basis)
        n = sends(c, basis)
        week_rows.append({"week": w.isoformat(), "partial": w < start or w + timedelta(days=7) > end,
                          "recent": w in recent_set, "sends": n,
                          **{k: c.get(k, 0) for k in ("delivered", "hard_bounce", "soft_bounce", "complaint",
                                                      "unsubscribe")},
                          "rates_pct": {m: pct(r[m]) for m in METRICS},
                          "judged": n >= args.min_weekly_sends, "_c": c, "_r": r})

    judged = [w for w in week_rows if w["judged"]]
    base_weeks = [w for w in judged if not w["recent"]]
    recent_weeks = [w for w in judged if w["recent"]]
    base_r = rates(total(w["_c"] for w in base_weeks), basis) if base_weeks else {m: None for m in METRICS}
    recent_r = rates(total(w["_c"] for w in recent_weeks), basis) if recent_weeks else {m: None for m in METRICS}
    has_baseline = len(base_weeks) >= RULES["min_baseline_weeks"]
    findings = []

    for m in METRICS:
        # Guard-rails: the recent pool and each recent week, then earlier weeks that have since recovered.
        level = crossed(m, recent_r[m])
        hot = [w["week"] for w in recent_weeks if crossed(m, w["_r"][m]) == "limit"]
        if level or hot:
            lvl = "limit" if level == "limit" or hot else "warn"
            findings.append({"priority": "high" if lvl == "limit" else "medium", "kind": "guardrail", "metric": m,
                             "level": lvl, "recent_pct": pct(recent_r[m]),
                             "threshold_pct": pct(limit(m, lvl)), "weeks": hot,
                             "message": f"{m.replace('_', ' ')} {pct(recent_r[m])}% over the last "
                                        f"{len(recent_weeks)} judged weeks; the rule-of-thumb {lvl} is "
                                        f"{pct(limit(m, lvl))}%"
                                        + (f"; weeks over the limit: {', '.join(hot)}" if hot else "")})
        elif recent_weeks:
            old = [w["week"] for w in base_weeks if crossed(m, w["_r"][m]) == "limit"]
            if old:
                findings.append({"priority": "low", "kind": "guardrail", "metric": m, "level": "limit",
                                 "recent_pct": pct(recent_r[m]), "threshold_pct": pct(limit(m, "limit")),
                                 "weeks": old,
                                 "message": f"{m.replace('_', ' ')} crossed the rule-of-thumb limit in earlier weeks "
                                            f"({', '.join(old)}) and has since recovered"})

        # Drift: the recent pool against the baseline pool.
        b, r = base_r[m], recent_r[m]
        if has_baseline and recent_weeks and b is not None and r is not None:
            pts = Fraction(str(RULES["drift_min_points"][m])) / 100
            if m == "delivery_rate":
                drifting = b - r >= pts
            else:
                drifting = r - b >= pts and r >= b * Fraction(str(args.drift_ratio))
            if drifting:
                findings.append({"priority": "medium", "kind": "drift", "metric": m, "recent_pct": pct(r),
                                 "baseline_pct": pct(b), "change_points": pct(r - b), "weeks": [],
                                 "message": f"{m.replace('_', ' ')} drifted from {pct(b)}% (baseline, "
                                            f"{len(base_weeks)} weeks) to {pct(r)}% (last {len(recent_weeks)} "
                                            "weeks) against the project's own history"})

        # Spikes: one week against the median judged week.
        if m == "delivery_rate" or not has_baseline:
            continue
        typical = median([w["_r"][m] for w in judged if w["_r"][m] is not None])
        for w in judged:
            x, events = w["_r"][m], w["_c"].get(NUMERATOR[m], 0)
            if x is None or typical is None or events < RULES["spike_min_events"]:
                continue
            if x >= typical * Fraction(str(RULES["spike_ratio"])) and x > typical:
                findings.append({"priority": "medium" if w["recent"] else "low", "kind": "spike", "metric": m,
                                 "week_pct": pct(x), "typical_pct": pct(typical), "events": events,
                                 "weeks": [w["week"]],
                                 "message": f"{m.replace('_', ' ')} spiked to {pct(x)}% in the week of {w['week']} "
                                            f"({events} events; a typical week is {pct(typical)}%). Break that week "
                                            "down by campaign to find the send"})

    # Breakdowns.
    out_breakdowns = {}
    window_judge = RULES["min_breakdown_sends"]
    for name, path in breakdowns:
        rows = table(path)
        if name in ("sender", "integration", "campaign"):
            grouped = {}
            for h, c in rows:
                key = domain(h) if name == "sender" else (NOT_RECORDED if h is None else str(h))
                g = grouped.setdefault(key, {})
                for k, v in c.items():
                    g[k] = g.get(k, 0) + v
            items = sorted((group_row(k, c, basis, window_judge) for k, c in grouped.items()),
                           key=lambda x: (-x["sends"], x["name"]))
            entry = {"rows": items}
            if name == "sender" and [i["name"] for i in items] == [NOT_RECORDED]:
                entry["note"] = "The campaign event has no sender on this project; a by-domain view isn't possible."
            if name == "campaign":
                if scenarios is not None:
                    typed = {}
                    for k, c in grouped.items():
                        t = "scenario" if k in scenarios else ("one-off campaign" if k not in (NOT_RECORDED, OTHER)
                                                               else k)
                        g = typed.setdefault(t, {})
                        for kk, v in c.items():
                            g[kk] = g.get(kk, 0) + v
                    entry["by_type"] = sorted((group_row(k, c, basis, window_judge) for k, c in typed.items()),
                                              key=lambda x: (-x["sends"], x["name"]))
                else:
                    entry["note"] = "Pass --scenarios (a saved search_scenarios list) to split scenarios from one-off campaigns."
                entry["rows"] = sorted(items, key=lambda x: (-problems(x), x["name"]))[:RULES["top_contributors"]]
            out_breakdowns[name] = entry
            for i in entry.get("by_type", []) + (items if name != "campaign" else entry["rows"]):
                for m, lvl in i["flags"].items():
                    findings.append({"priority": "medium" if lvl == "limit" else "low", "kind": "breakdown",
                                     "metric": m, "level": lvl, "breakdown": name, "group": i["name"],
                                     "group_pct": i["rates_pct"][m], "threshold_pct": pct(limit(m, lvl)), "weeks": [],
                                     "message": f"{name} {i['name']}: {m.replace('_', ' ')} {i['rates_pct'][m]}% over "
                                                f"the window on {i['sends']} sends (rule-of-thumb {lvl} "
                                                f"{pct(limit(m, lvl))}%)"})
        elif name == "new_audience":
            new = total(c for _, c in rows)
            est = {k: max(window_total.get(k, 0) - new.get(k, 0), 0) for k in set(window_total) | set(new)}
            items = [group_row("new to email in the window", new, basis, window_judge),
                     group_row("established", est, basis, window_judge)]
            entry = {"rows": items}
            if any(new.get(k, 0) > window_total.get(k, 0) for k in new):
                entry["note"] = ("The new-audience counts exceed the window totals for some statuses: the two queries "
                                 "probably cover different windows.")
            out_breakdowns[name] = entry
            for i in items:
                for m, lvl in i["flags"].items():
                    findings.append({"priority": "medium" if lvl == "limit" else "low", "kind": "breakdown",
                                     "metric": m, "level": lvl, "breakdown": name, "group": i["name"],
                                     "group_pct": i["rates_pct"][m], "threshold_pct": pct(limit(m, lvl)), "weeks": [],
                                     "message": f"{i['name']} recipients: {m.replace('_', ' ')} {i['rates_pct'][m]}% "
                                                f"(rule-of-thumb {lvl} {pct(limit(m, lvl))}%)"})
        else:  # spike:<week>
            week = name.split(":", 1)[1]
            items = [group_row(NOT_RECORDED if h is None else str(h), c, basis, 0) for h, c in rows]
            all_problems = sum(problems(i) for i in items)
            items = sorted(items, key=lambda x: (-problems(x), x["name"]))[:RULES["top_contributors"]]
            for i in items:
                i["share_of_week_problems_pct"] = pct(Fraction(problems(i), all_problems)) if all_problems else None
            out_breakdowns[name] = {"week": week, "rows": items}

    findings.sort(key=lambda f: (PRIORITY[f["priority"]], KIND[f["kind"]], METRICS.index(f["metric"]),
                                 f.get("breakdown", ""), str(f.get("group", "")), f["weeks"][:1]))
    for w in week_rows:
        del w["_c"], w["_r"]
    return {
        "ok": True,
        "window": {"start": start.isoformat(), "end_exclusive": end.isoformat(), "days_with_data": len(days)},
        "sends_basis": basis,
        "totals": {"sends": sends(window_total, basis),
                   **{k: window_total.get(k, 0) for k in ("delivered", "hard_bounce", "soft_bounce", "complaint",
                                                          "unsubscribe")},
                   "rates_pct": {m: pct(v) for m, v in rates(window_total, basis).items()}},
        "baseline": {"weeks": len(base_weeks), "enough": has_baseline,
                     "rates_pct": {m: pct(v) for m, v in base_r.items()}},
        "recent": {"weeks": len(recent_weeks), "rates_pct": {m: pct(v) for m, v in recent_r.items()}},
        "low_volume_weeks": [w["week"] for w in week_rows if not w["judged"]],
        "weeks": week_rows,
        "findings": findings,
        "counts": {p: sum(1 for f in findings if f["priority"] == p) for p in PRIORITY},
        "breakdowns": out_breakdowns,
    }


def breakdown_arg(text):
    name, sep, path = text.partition("=")
    ok = name in ("sender", "integration", "campaign", "new_audience")
    if name.startswith("spike:"):
        try:
            ok = date.fromisoformat(name.split(":", 1)[1]).weekday() == 0
        except ValueError:
            ok = False
    if not sep or not path or not ok:
        raise argparse.ArgumentTypeError("use NAME=FILE with NAME sender, integration, campaign, new_audience or "
                                         f"spike:<YYYY-MM-DD, a Monday>; got {text!r}")
    return name, path


def iso_date(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {text!r}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--daily", required=True, help="saved daily x status EQL cross-tab")
    ap.add_argument("--breakdown", action="append", type=breakdown_arg, default=[], help="NAME=FILE: sender, integration, campaign, new_audience or spike:<monday>; repeatable")
    ap.add_argument("--scenarios", help="saved search_scenarios list, to type campaign_ids as scenarios")
    ap.add_argument("--start", type=iso_date, help="first day of the queried window (YYYY-MM-DD)")
    ap.add_argument("--end", type=iso_date, help="day after the queried window (YYYY-MM-DD, exclusive)")
    ap.add_argument("--utc-offset", type=float,
                    help="the project's offset from UTC in hours (e.g. 13 for New Zealand summer); dates timestamp "
                         "headers directly instead of counting from --start")
    ap.add_argument("--recent-weeks", type=int, default=RULES["recent_weeks"],
                    help=f"weeks compared with the baseline (default {RULES['recent_weeks']}, from references/rules.json)")
    ap.add_argument("--min-weekly-sends", type=int, default=RULES["min_weekly_sends"],
                    help=f"weeks below this are not judged (default {RULES['min_weekly_sends']}, from references/rules.json)")
    ap.add_argument("--drift-ratio", type=float, default=RULES["drift_ratio"],
                    help=f"recent / baseline ratio that counts as drift (default {RULES['drift_ratio']}, from references/rules.json)")
    ap.add_argument("--out", help="write the JSON here (a path in your working folder) instead of printing it")
    a = ap.parse_args()
    if a.recent_weeks < 1:
        fail("--recent-weeks must be at least 1.")

    names = [n for n, _ in a.breakdown]
    if len(names) != len(set(names)):
        fail("each --breakdown NAME can be given once.")
    scenarios = scenario_ids(a.scenarios) if a.scenarios else None
    result = analyse(table(a.daily), a.breakdown, scenarios, a)
    text = json.dumps(result, indent=1, ensure_ascii=False)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"can't write {a.out} ({e}).")
        print(json.dumps({"ok": True, "out": a.out, "counts": result["counts"]}))
    else:
        print(text)


if __name__ == "__main__":
    main()
