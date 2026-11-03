#!/usr/bin/env python3
"""Rate Bloomreach Discovery API health from saved get_discovery_api_requests and get_discovery_unique_visitors results.

Usage:
  python3 api_health.py --series total=total.json --series type:keyword=keyword.json --series status:5xx=5xx.json
         [--series status:4xx=4xx.json] [--series env:staging=staging.json] [--series site:<name>=site.json]
         [--series region:<name>=region.json] [--muv muv.json] [--today 2026-11-03] [--out health.json]

Each --series is NAME=FILE, where FILE is one saved daily get_discovery_api_requests result made with one filter
(the API applies one filter per call), and NAME says which:
  total               no filter (required)
  type:<request type> request_type:<request type>, e.g. type:keyword, type:category, type:suggest
  status:5xx, status:4xx   status_code:5xx, status_code:4xx
  env:staging         environment:staging
  site:<name>, region:<name>   site:<name>, region:<name>
--muv is a saved get_discovery_unique_visitors result (monthly). --today (default: today, UTC) marks the current,
partial day and month, which are never judged.

Each of the last recent_days complete days is compared with the same weekday in the baseline_days before them:
volume drops, surges and stopped series (total, each type, 'other' = total minus the listed types, sites and
regions); 4xx and 5xx share of all requests against fixed limits and against their own baseline; and staging's
share of all traffic. Monthly unique visitors are compared with the contracted limit, with a forecast for the
current month from recent complete months. Thresholds are in references/rules.json. Prints JSON with an overall
RED / AMBER / GREEN status and one entry per check. Standard library only; no network access.
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
ORDER = {"RED": 0, "AMBER": 1, "GREEN": 2}
KINDS = ("total", "type", "status", "env", "site", "region")


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def tool_error(text):
    """A Loomi Connect error, safe to show: an error about the account name can list every account the user can
    access (many of them other customers), so it's never repeated."""
    text = str(text or "no error text")
    if "account" in text.lower() and text.count(",") >= 3:
        return ("Loomi Connect returned an error about the account name; it isn't repeated because it can list "
                "other accounts. Ask the user to check the account name.")
    return text[:200]


def results(path):
    """The results rows of a saved Discovery usage result, after checking it isn't an error returned as data."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {tool_error(d.get('error'))} "
                 "This check couldn't run; don't treat it as 'nothing found'.")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    inner = data.get("data") if isinstance(data, dict) else None
    if isinstance(inner, dict) and inner.get("isSuccessful") is False:
        fail(f"{path}: the usage API reported a failure. This check couldn't run.")
    body = (inner or {}).get("body") if isinstance(inner, dict) else None
    rows = (body or {}).get("results") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        fail(f"{path}: no data.body.results in the file. Pass the whole saved tool result.")
    if not all(isinstance(r, dict) for r in rows):
        fail(f"{path}: data.body.results holds something other than result rows.")
    return rows


def number(total, key):
    try:
        v = float(((total or {}).get(key) or {}).get("value"))
    except (TypeError, ValueError):
        return None
    return int(v) if v.is_integer() else v


def daily(path, today):
    out = {}
    for r in results(path):
        try:
            day = date.fromisoformat(str(r.get("time_period_start"))[:10])
        except ValueError:
            fail(f"{path}: a row has no YYYY-MM-DD time_period_start. Use granularity 'daily'.")
        if day < today:
            out[day] = number(r.get("total"), "request_count")
    if not out:
        fail(f"{path}: no complete days before {today}. Ask for a longer window.")
    return out


def series_arg(text):
    name, sep, path = text.partition("=")
    kind = name.split(":", 1)[0]
    if not sep or not path or kind not in KINDS or (kind != "total" and ":" not in name):
        raise argparse.ArgumentTypeError(f"use NAME=FILE with NAME total, type:<x>, status:4xx, status:5xx, env:staging, "
                                         f"site:<x> or region:<x>; got {text!r}")
    return name, path


def iso_date(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {text!r}")


def worst(statuses):
    return min(statuses, key=lambda s: ORDER[s]) if statuses else "GREEN"


def weekday_base(series, day, baseline):
    same = [series[d] for d in baseline if d.weekday() == day.weekday() and series.get(d) is not None]
    pool = same or [series[d] for d in baseline if series.get(d) is not None]
    return sum(pool) / len(pool) if pool else None


def volume_check(name, series, recent, baseline):
    flags, small = [], True
    for d in recent:
        v, base = series.get(d), weekday_base(series, d, baseline)
        if v is None or base is None or base < RULES["min_daily_requests"]:
            continue
        small = False
        if v == 0:
            flags.append(("RED", d, f"no requests on {d} (usually about {base:,.0f})"))
        elif (1 - v / base) * 100 >= RULES["volume_red_drop_pct"]:
            flags.append(("RED", d, f"{v:,.0f} on {d}, {(1 - v / base) * 100:.0f}% below its usual {base:,.0f}"))
        elif (1 - v / base) * 100 >= RULES["volume_amber_drop_pct"]:
            flags.append(("AMBER", d, f"{v:,.0f} on {d}, {(1 - v / base) * 100:.0f}% below its usual {base:,.0f}"))
        elif v / base >= RULES["volume_surge_ratio"]:
            flags.append(("AMBER", d, f"{v:,.0f} on {d}, {v / base:.1f}× its usual {base:,.0f}"))
    if small:
        return {"area": "volume", "series": name, "status": "GREEN", "evidence": "too little traffic to judge"}
    return result("volume", name, flags, "steady against the same weekdays")


def result(area, name, flags, ok_text):
    if not flags:
        return {"area": area, "series": name, "status": "GREEN", "evidence": ok_text}
    status = worst([f[0] for f in flags])
    top = sorted(flags, key=lambda f: (ORDER[f[0]], f[1]))[0]
    return {"area": area, "series": name, "status": status, "date": top[1].isoformat(), "evidence": top[2],
            "flagged_days": [{"date": f[1].isoformat(), "status": f[0]} for f in sorted(flags, key=lambda f: f[1])]}


def share(part, total, days):
    p = sum(part.get(d) or 0 for d in days)
    t = sum(total.get(d) or 0 for d in days)
    return p / t * 100 if t else None


def error_check(name, errors, total, recent, baseline):
    code = name.split(":", 1)[1]
    amber, red = RULES[f"error_{code}_amber_pct"], RULES[f"error_{code}_red_pct"]
    base = share(errors, total, baseline)
    flags = []
    for d in recent:
        e, t = errors.get(d), total.get(d)
        if e is None or not t:
            continue
        rate = e / t * 100
        text = f"{e:,.0f} {code} on {d} ({rate:.2f}% of requests; usually {base or 0:.2f}%)"
        if rate >= red:
            flags.append(("RED", d, text))
        elif rate >= amber:
            flags.append(("AMBER", d, text))
        elif e >= RULES["min_error_count"] and (not base or rate >= RULES["error_spike_ratio"] * base):
            flags.append(("AMBER", d, text + ", a spike"))
    return result("errors", name, flags, f"{code} share {share(errors, total, recent) or 0:.2f}% (usually {base or 0:.2f}%)")


def staging_check(staging, total, recent, baseline):
    base = share(staging, total, baseline) or 0
    flags = []
    for d in recent:
        s, t = staging.get(d), total.get(d)
        if s is None or not t:
            continue
        pct = s / t * 100
        text = f"staging is {pct:.1f}% of requests on {d} (usually {base:.1f}%)"
        above_base = pct >= RULES["staging_baseline_multiple"] * base
        if pct >= RULES["staging_share_red_pct"] and above_base:
            flags.append(("RED", d, text))
        elif pct >= RULES["staging_share_amber_pct"] and above_base:
            flags.append(("AMBER", d, text))
    return result("staging", "env:staging", flags, f"staging share {share(staging, total, recent) or 0:.1f}% (usually {base:.1f}%)")


def muv_check(path, today):
    this_month = today.strftime("%Y-%m")
    months = []
    for r in results(path):
        m = str(r.get("time_period_start"))[:7]
        if m < this_month:
            months.append((m, number(r.get("total"), "muv"), number(r.get("total"), "contracted_muv")))
    months.sort()
    # The previous month's figure arrives on the 2nd of the next month; until then it reads 0.
    if months and not months[-1][1]:
        months = months[:-1]
    if not months:
        return {"area": "contract", "series": "muv", "status": "GREEN", "evidence": "no complete month with data yet"}, None
    contract = next((c for _, _, c in reversed(months) if c), None)
    recent = [v for _, v, _ in months[-RULES["muv_forecast_months"]:] if v]
    forecast = sum(recent) / len(recent) if recent else None
    last_m, last_v, _ = months[-1]
    summary = {"months": [{"month": m, "muv": v, "contracted_muv": c or None,
                           "usage_pct": round(v / contract * 100, 1) if contract and v is not None else None}
                          for m, v, c in months],
               "contracted_muv": contract, "forecast_this_month": round(forecast) if forecast else None,
               "forecast_basis": f"average of the last {len(recent)} complete month(s)"}
    if not contract:
        return {"area": "contract", "series": "muv", "status": "GREEN",
                "evidence": f"{last_m}: {last_v:,.0f} unique visitors; no contracted limit (not on MUV-based pricing)"}, summary
    flags = []
    for label, v in ((last_m, last_v), (f"{this_month} forecast", forecast)):
        pct = v / contract * 100 if v else 0
        text = f"{label}: {v:,.0f} unique visitors, {pct:.0f}% of the contracted limit"
        if pct >= RULES["muv_red_pct"]:
            flags.append(("RED", label, text))
        elif pct >= RULES["muv_amber_pct"]:
            flags.append(("AMBER", label, text))
    if not flags:
        return {"area": "contract", "series": "muv", "status": "GREEN",
                "evidence": f"{last_m}: {last_v / contract * 100:.0f}% of the contracted limit; forecast "
                            f"{(forecast or 0) / contract * 100:.0f}%"}, summary
    status = worst([f[0] for f in flags])
    top = sorted(flags, key=lambda f: ORDER[f[0]])[0]
    return {"area": "contract", "series": "muv", "status": status, "date": top[1], "evidence": top[2]}, summary


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series", action="append", type=series_arg, default=[], help="NAME=FILE (repeat)")
    ap.add_argument("--muv", help="saved get_discovery_unique_visitors result")
    ap.add_argument("--today", type=iso_date, help="today's date, YYYY-MM-DD (default: today, UTC)")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    today = a.today or datetime.now(timezone.utc).date()
    names = [n for n, _ in a.series]
    if len(set(names)) != len(names):
        fail("each --series name can only be given once")
    if a.series and "total" not in names:
        fail("--series total=<file> (no filter) is required: error and staging shares and 'other' are worked out from it")
    if not a.series and not a.muv:
        fail("give at least --series total=<file> or --muv <file>")
    series = {n: daily(p, today) for n, p in a.series}
    checks, notes, recent, baseline = [], [], [], []
    if series:
        total = series["total"]
        days = sorted(total)
        recent = days[-RULES["recent_days"]:]
        start = recent[0] - timedelta(days=RULES["baseline_days"])
        baseline = [d for d in days if start <= d < recent[0]]
        if len(baseline) < RULES["min_baseline_days"]:
            notes.append(f"Only {len(baseline)} baseline day(s); fetch {RULES['baseline_days'] + RULES['recent_days']} days "
                         "for a fair comparison.")
        types = {n: s for n, s in series.items() if n.startswith("type:")}
        if types:
            series["type:other"] = {d: max(0.0, (total.get(d) or 0) - sum(s.get(d) or 0 for s in types.values()))
                                    for d in days}
        for name in sorted(series, key=lambda n: (KINDS.index(n.split(":")[0]), n)):
            s = series[name]
            if name.startswith("status:"):
                if name not in ("status:4xx", "status:5xx"):
                    notes.append(f"{name} isn't checked; use status:4xx or status:5xx.")
                    continue
                checks.append(error_check(name, s, total, recent, baseline))
            elif name == "env:staging":
                checks.append(staging_check(s, total, recent, baseline))
            elif name.startswith("env:"):
                notes.append(f"{name} isn't checked; only env:staging is.")
            else:
                checks.append(volume_check(name, s, recent, baseline))
    muv = None
    if a.muv:
        check, muv = muv_check(a.muv, today)
        checks.append(check)
    checks.sort(key=lambda c: (ORDER[c["status"]], c["area"], c["series"]))
    out = {"ok": True, "today": today.isoformat(), "overall": worst([c["status"] for c in checks]),
           "recent_days": [d.isoformat() for d in recent],
           "baseline": {"from": baseline[0].isoformat(), "to": baseline[-1].isoformat()} if baseline else None,
           "checks": checks, "muv": muv, "notes": notes}
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
