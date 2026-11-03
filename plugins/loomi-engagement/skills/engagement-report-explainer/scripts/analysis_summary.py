#!/usr/bin/env python3
"""Summarise saved Bloomreach Engagement analysis responses for the report explainer skill.

Reads JSON the assistant has already fetched with Loomi Connect. It never calls
the network. Standard library only.

Usage:
    python3 scripts/analysis_summary.py dashboard DASHBOARD_JSON [--tz ZONE]
    python3 scripts/analysis_summary.py result CALCULATE_REPORT_JSON [--tz ZONE]
    python3 scripts/analysis_summary.py windows DEFINITION_JSON [--today YYYY-MM-DD] [--tz ZONE]

--tz       the project's IANA time zone (for example Pacific/Auckland), used to
           turn timestamps into dates. Without it, daily buckets are read
           correctly for any zone from UTC-10 to UTC+13, and other dates are UTC.

dashboard  a saved `search_dashboards` response fetched with a dashboard_id.
           Prints components in display order (by y, then x), skipping spacer
           text blocks. HTML content is never printed, only its size.
result     a saved `calculate_report` response. Prints a table with one column
           per metric (named from the embedded definition) and timestamp keys
           converted to dates.
windows    any saved definition (report, funnel, trend, segmentation, or a
           calculate_report response). Prints every date filter and
           conversion window in plain English, and flags fixed windows that
           ended more than 30 days ago and filters that are switched off.

Editor names and email addresses in the responses are never printed.
"""
import argparse
import datetime as dt
import json
import math
import sys

STALE_DAYS = 30
TZ = None  # set from --tz
# Daily buckets start at local midnight. Adding 13 hours before taking the UTC
# date gives the local date for any offset above UTC-11 up to UTC+13. No single
# shift covers UTC-11 to UTC+14 (that span is 25 hours), so those need --tz.
BUCKET_SHIFT = 13 * 3600
NO_TZ_NOTE = ("Dates assume the project's time zone is between UTC-10 and UTC+13 "
              "(pass --tz with its IANA name otherwise).")


def unwrap(obj):
    """Strip the {result: {data: ...}} / {data: ...} envelopes Loomi Connect uses."""
    for _ in range(3):
        if isinstance(obj, dict) and isinstance(obj.get("result"), dict):
            obj = obj["result"]
        if isinstance(obj, dict) and obj.get("data") is not None and "as_dict" not in obj:
            obj = obj["data"]
    return obj


NA = {"", "na", "n/a", "-", "—", "null"}


def num(x):
    """Number or None. Strings may carry $ £ €, thousands commas or a trailing %."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x) if math.isfinite(x) else None
    if not isinstance(x, str):
        return None
    s = x.strip()
    if s.lower() in NA:
        return None
    for ch in ",$£€":
        s = s.replace(ch, "")
    s = s.strip()
    if s.endswith("%"):
        s = s[:-1].strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for o in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(o, dict) and o.get("success") is False:
            sys.exit(f"{path}: Loomi Connect returned an error: {o.get('error') or 'no error text'}. "
                     "This check couldn't run; don't treat it as 'nothing found'.")
    return data


def bucket_date(ts):
    """Date of a bucket that starts at local midnight in the project's time zone."""
    if TZ:
        return dt.datetime.fromtimestamp(int(float(ts)), tz=TZ).date()
    return dt.datetime.fromtimestamp(int(float(ts)) + BUCKET_SHIFT, tz=dt.timezone.utc).date()


def fmt_date(ts):
    return dt.datetime.fromtimestamp(int(float(ts)), tz=TZ or dt.timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- dashboard

def cmd_dashboard(args):
    data = unwrap(load(args.file))
    comps = data.get("components") or []
    print(f"Dashboard: {data.get('name')}  (archived={data.get('archived')}, "
          f"home={data.get('home')}, shared={data.get('shared')}, "
          f"last edited {fmt_date(data['edited']) if data.get('edited') else 'unknown'})")

    def key(c):
        p = c.get("position") or {}
        return (p.get("y", 0), p.get("x", 0))

    shown = 0
    spacers = 0
    for c in sorted(comps, key=key):
        t = c.get("type")
        p = c.get("position") or {}
        text = c.get("text")
        if t == "text" and (text is None or not str(text).strip()):
            spacers += 1
            continue
        shown += 1
        where = f"row {p.get('y')}, col {p.get('x')}, width {p.get('width')}"
        if t == "text":
            detail = f'heading/note: "{str(text).strip()[:80]}"'
        elif t == "html":
            detail = f"HTML block ({len(text or '')} chars, evaluate={c.get('evaluate')}); summarise, don't paste"
        else:
            overrides = [k for k in ("date_filter", "comparison", "goal") if c.get(k)]
            detail = f"id {c.get('id')}"
            if c.get("display"):
                detail += f", shown as {c['display']}"
            if overrides:
                detail += f", tile overrides: {', '.join(overrides)}"
            if t == "metric":
                detail += " (saved KPI metric: no read tool)"
        print(f"{shown:>2}. [{t}] {where}: {detail}")
    print(f"\n{shown} components shown, {spacers} spacer text blocks skipped.")
    ids = {}
    for c in comps:
        if c.get("id"):
            ids.setdefault(c.get("type"), []).append(c["id"])
    for t, lst in ids.items():
        print(f"{t} component ids: {', '.join(lst)}")


# ---------------------------------------------------------------- result

def metric_names(defn):
    server = (defn or {}).get("server") or {}
    return [m.get("name") or f"metric {i + 1}" for i, m in enumerate(server.get("metrics") or [])]


def is_timestamp_rows(defn):
    server = (defn or {}).get("server") or {}
    rows = server.get("rows") or []
    return bool(rows) and (rows[0].get("attribute") or {}).get("type") == "timestamp"


def cmd_result(args):
    raw = load(args.file)
    data = unwrap(raw)
    as_dict = data.get("as_dict")
    defn = data.get("definition") or {}
    names = metric_names(defn)
    print(f"Report: {defn.get('name', '(name not in response)')}")
    if not as_dict:
        print("Empty result. The cache may be cold (open the report in the UI), "
              "or the definition matches nothing.")
        return 0
    if not isinstance(as_dict, dict):
        print("Unexpected result shape (a parametrized preview?). Read it manually.")
        return 0
    ts_rows = is_timestamp_rows(defn)
    rows = list(as_dict.items())
    if ts_rows:
        rows.sort(key=lambda kv: float(kv[0]))
    header = ["date" if ts_rows else "row"] + (names or ["value"])
    print(" | ".join(header))
    totals = None
    nested = False
    missing = 0
    for k, v in rows:
        label = bucket_date(k).isoformat() if ts_rows else k
        vals = v if isinstance(v, list) else [v]
        if any(isinstance(x, (dict, list)) for x in vals):
            nested = True
            print(f"{label} | {json.dumps(vals)[:120]}")
            continue
        print(" | ".join([str(label)] + [str(x) for x in vals]))
        nums = [num(x) for x in vals]
        missing += sum(1 for x in nums if x is None)
        nums = [x or 0 for x in nums]
        totals = nums if totals is None else [a + b for a, b in zip(totals, nums)]
    if nested:
        print("\nNested values (rows and columns): read the shape manually.")
    elif totals is not None:
        print(" | ".join(["TOTAL (sum; not meaningful for rates or averages)"] + [str(int(t) if t == int(t) else round(t, 4)) for t in totals]))
        zero = sum(1 for _, v in rows if all((num(x) or 0) == 0 for x in (v if isinstance(v, list) else [v])))
        print(f"\n{len(rows)} rows, {zero} all-zero.")
        if missing:
            print(f"{missing} value(s) were empty or not numbers and count as 0 in the totals.")
        if ts_rows:
            last = bucket_date(rows[-1][0])
            today = dt.datetime.now(TZ).date() if TZ else dt.date.today()
            if last >= today:
                print("The last bucket is today, so it is incomplete.")
            print(f"Dates in {TZ.key}." if TZ else NO_TZ_NOTE)
    return 0


# ---------------------------------------------------------------- windows

def describe_window(df, today):
    if not isinstance(df, dict):
        return "not set", None
    if not df.get("enabled"):
        dur = df.get("duration") or {}
        note = ""
        if dur.get("count"):
            note = f" (a {dur['count']} {dur.get('units')} window is configured but switched off)"
        return "all time" + note, "off"
    if df.get("absolute"):
        f, t = df.get("from_date"), df.get("to_date")
        text = f"fixed: {fmt_date(f) if f else 'start'} to {fmt_date(t) if t else 'now'}"
        if t:
            age = (today - dt.datetime.fromtimestamp(int(t), tz=TZ or dt.timezone.utc).date()).days
            if age > STALE_DAYS:
                return text + f" (ended {age} days ago)", "stale"
        return text, None
    dur = df.get("duration") or {}
    text = f"rolling: last {dur.get('count')} {dur.get('units')}"
    if df.get("offset"):
        text += f", offset {json.dumps(df['offset'])}"
    return text, None


def walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            if k in ("date_filter", "date") and isinstance(v, dict) and "enabled" in v:
                yield p, "date", v
            elif k == "duration_filter" and isinstance(v, dict):
                yield p, "conversion", v
            else:
                yield from walk(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


def cmd_windows(args):
    data = unwrap(load(args.file))
    if isinstance(data, dict) and "definition" in data and "as_dict" in data:
        data = data["definition"]
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    print(f"Analysis: {data.get('name')}  (last edited "
          f"{fmt_date(data['edited']) if data.get('edited') else 'unknown'})")
    flags = 0
    for path, kind, v in walk(data):
        if kind == "conversion":
            if v.get("enabled"):
                d = v.get("duration") or {}
                text, flag = f"conversion window: {d.get('count')} {d.get('units')}", None
            else:
                text, flag = "conversion window: none (no time limit between steps)", "off"
        else:
            text, flag = describe_window(v, today)
        mark = {"stale": "  <-- STALE", "off": "  <-- check"}.get(flag, "")
        if flag:
            flags += 1
        print(f"{path}: {text}{mark}")
    print(f"\n{flags} window(s) to mention as caveats.")
    print(f"Dates in {TZ.key}." if TZ else "Fixed dates are shown in UTC (pass --tz for the project's time zone).")
    return 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    global TZ
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("file")
    common.add_argument("--tz", help="the project's IANA time zone, for example Europe/London")
    sub.add_parser("dashboard", parents=[common])
    sub.add_parser("result", parents=[common])
    w = sub.add_parser("windows", parents=[common])
    w.add_argument("--today")
    args = ap.parse_args()
    if args.tz:
        try:
            from zoneinfo import ZoneInfo
            TZ = ZoneInfo(args.tz)
        except Exception:  # unknown name, or no time zone data on this machine
            sys.exit(f"Unknown time zone {args.tz!r}: use an IANA name such as Europe/London, or leave --tz out.")
    fn = {"dashboard": cmd_dashboard, "result": cmd_result, "windows": cmd_windows}[args.cmd]
    sys.exit(fn(args) or 0)


if __name__ == "__main__":
    main()
