#!/usr/bin/env python3
"""Work out who can be reached by email, SMS and push, and how consent is changing, from saved aggregate counts.

Usage:
  python3 contactability_report.py --base FILE_OR_NUMBER
      [--has-id CHANNEL=FILE_OR_NUMBER ...] [--reachable CHANNEL=FILE_OR_NUMBER ...]
      [--any-reachable FILE_OR_NUMBER] [--high-value FILE_OR_NUMBER] [--high-value-unreachable FILE_OR_NUMBER]
      [--consent-trend FILE] [--consent-categories FILE] [--consent-by-category FILE]
      [--holders CATEGORY=FILE_OR_NUMBER ...] [--out report.json]

Every FILE_OR_NUMBER is a number or a saved execute_analytics_eql result for a customer count
(every row's values are added up, null rows included; an empty rows list is 0). NAME=VALUE
inputs are split on the first "=".
  --base                    customers in the base (for example buyers in the last 365 days)
  --has-id CHANNEL=...      customers in the base with the channel's identifier (email address,
                            phone number, push token)
  --reachable CHANNEL=...   customers in the base with the identifier and the consent
  --any-reachable           customers in the base reachable on at least one channel
  --high-value              high-value customers (for example lifetime spend over 3 x AOV)
  --high-value-unreachable  high-value customers reachable on no measured channel
  --consent-trend           EQL cross-tab of consent events: rows = month (event consent timestamp
                            ... format year month), columns = action
  --consent-categories      the saved get_consent_settings response
  --consent-by-category     EQL cross-tab of consent events: rows = category, columns = action
  --holders CATEGORY=...    customers who hold consent in a category (has consent <id>)

Prints JSON (or writes it to --out): channels (identifier share, reachable share, consent gap),
any-channel reach, high-value reach, the monthly opt-in and opt-out trend, each consent category's
use, and findings with priority high, medium or low. Thresholds come from references/rules.json.
It works only on counts: it never sees or lists a customer.

Standard library only; no network access. Writes nothing to Bloomreach.
"""
import argparse
import datetime
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
MISSING = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}
PRIORITY = {"high": 0, "medium": 1, "low": 2}
# Monthly buckets start at local midnight in the project's time zone, which can be up to 14 hours
# either side of the UTC month start. Shifting by two days lands safely inside the right month.
MONTH_SHIFT_SECONDS = 2 * 86400


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


def load(path):
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
            fail(f"{path}: Loomi Connect returned an error: {data.get('error') or 'no error text'}. "
                 "This check couldn't run; don't treat it as 'nothing found'.")
        if isinstance(data, dict) and "success" in data and "data" in data and not isinstance(data.get("rows"), list):
            data = data["data"]
    return data


def report(data, path):
    """The report body of an EQL result: a dict with rows (and columns for a cross-tab)."""
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        fail(f"{path}: no EQL rows found; save the execute_analytics_eql result.")
    return data


def pair(text):
    """NAME=VALUE, split on the first "="."""
    name, sep, value = text.partition("=")
    if not sep or not name.strip() or not value.strip():
        raise argparse.ArgumentTypeError(f"expected NAME=FILE_OR_NUMBER, got {text!r}")
    return name.strip(), value.strip()


def count_of(value, label):
    """A count from a number or a saved EQL customer count."""
    if os.path.exists(value):
        rep = report(load(value), value)
        return sum(number(v) or 0.0 for r in rep["rows"] if isinstance(r, dict) for v in r.get("values") or [])
    x = number(value)
    if x is None or x < 0:
        fail(f"{label}: {value!r} is neither a file nor a count.")
    return x


def header_text(headers):
    vals = [h.get("value") if isinstance(h, dict) else h for h in headers or []]
    return " / ".join("null" if v is None else str(v) for v in vals) if vals else "total"


def crosstab(path):
    """{row label: {column label: value}} from an EQL cross-tab, keeping the raw first row header."""
    rep = report(load(path), path)
    cols = [header_text(c) for c in rep.get("columns") or [[]]] or ["total"]
    out = []
    for r in rep["rows"]:
        if not isinstance(r, dict):
            continue
        heads = r.get("headers") or []
        raw = heads[0].get("value") if heads and isinstance(heads[0], dict) else (heads[0] if heads else None)
        vals = r.get("values") or []
        out.append((raw, {cols[i] if i < len(cols) else f"column {i}": number(v) or 0.0 for i, v in enumerate(vals)}))
    return out


def month_key(raw):
    x = number(raw) if not isinstance(raw, str) or not re.match(r"^\d{4}-\d{2}", raw) else None
    if x is not None and x > 10**8:
        return datetime.datetime.fromtimestamp(x + MONTH_SHIFT_SECONDS, datetime.timezone.utc).strftime("%Y-%m")
    if isinstance(raw, str) and re.match(r"^\d{4}-\d{2}", raw):
        return raw[:7]
    return None


def split_actions(cells, rules):
    ins = {a.lower() for a in rules["opt_in_actions"]}
    outs = {a.lower() for a in rules["opt_out_actions"]}
    a = b = other = 0.0
    for col, v in cells.items():
        c = col.lower()
        if c in ins:
            a += v
        elif c in outs:
            b += v
        else:
            other += v
    return a, b, other


def share(part, whole):
    return None if part is None or not whole else round(part / whole, 4)


def channel_sort(names, rules):
    order = rules["channel_order"]
    return sorted(names, key=lambda c: (order.index(c) if c in order else len(order), c))


def build(a, rules):
    findings = []

    def add(priority, kind, text, **extra):
        findings.append({"priority": priority, "kind": kind, "finding": text, **extra})

    base = count_of(a.base, "--base")
    if not base:
        fail("--base is 0: there's nobody to measure. Check the base query.")
    has_id = {c: count_of(v, f"--has-id {c}") for c, v in a.has_id}
    reach = {c: count_of(v, f"--reachable {c}") for c, v in a.reachable}

    channels = []
    for c in channel_sort(set(has_id) | set(reach), rules):
        hid, rch = has_id.get(c), reach.get(c)
        gap = None if hid is None or rch is None else max(hid - rch, 0.0)
        row = {"channel": c, "has_identifier": hid, "has_identifier_share": share(hid, base),
               "reachable": rch, "reachable_share": share(rch, base), "consent_gap": gap, "consent_gap_share": share(gap, base)}
        channels.append(row)
        primary = c in rules["primary_channels"]
        if rch is None:
            add("low", "not_measured", f"{c}: reachable count not measured.", channel=c)
            continue
        if hid is not None and rch > hid:
            add("low", "data_check", f"{c}: more reachable ({rch:,.0f}) than with an identifier ({hid:,.0f}); check the two queries use the same base.", channel=c)
        s = rch / base
        if s < rules["low_reach_share"]:
            add("high" if primary else "medium", "low_reach", f"{c}: only {s:.0%} of the base can be reached.", channel=c, share=round(s, 4))
        elif s < rules["medium_reach_share"]:
            add("medium" if primary else "low", "limited_reach", f"{c}: {s:.0%} of the base can be reached.", channel=c, share=round(s, 4))
        if gap is not None and gap / base >= rules["consent_gap_share"]:
            add("medium", "consent_gap", f"{c}: {gap / base:.0%} of the base have the identifier but no consent; a re-permission or preference-centre opportunity.",
                channel=c, share=round(gap / base, 4))

    any_reach = count_of(a.any_reachable, "--any-reachable") if a.any_reachable else None
    if any_reach is not None:
        s = any_reach / base
        if s < rules["medium_reach_share"]:
            add("high" if s < rules["low_reach_share"] else "medium", "unreachable",
                f"{1 - s:.0%} of the base can't be reached on any measured channel.", share=round(1 - s, 4))

    high_value = None
    if a.high_value and a.high_value_unreachable:
        hv, hvu = count_of(a.high_value, "--high-value"), count_of(a.high_value_unreachable, "--high-value-unreachable")
        s = share(hvu, hv)
        high_value = {"customers": hv, "unreachable": hvu, "unreachable_share": s}
        if s is not None:
            p = "high" if s >= rules["high_value_unreachable_high"] else "medium" if s >= rules["high_value_unreachable_medium"] else "low"
            add(p, "high_value_unreachable", f"{s:.0%} of high-value customers ({hvu:,.0f}) can't be reached on any measured channel.", share=s)
    elif a.high_value or a.high_value_unreachable:
        fail("--high-value and --high-value-unreachable go together.")

    trend = None
    if a.consent_trend:
        months = {}
        for raw, cells in crosstab(a.consent_trend):
            key = month_key(raw)
            if key is None:
                continue
            i, o, other = split_actions(cells, rules)
            m = months.setdefault(key, {"month": key, "opt_ins": 0.0, "opt_outs": 0.0, "other": 0.0})
            m["opt_ins"] += i
            m["opt_outs"] += o
            m["other"] += other
        rows = [dict(m, net=m["opt_ins"] - m["opt_outs"]) for _, m in sorted(months.items())]
        trend = rows
        total = sum(r["opt_ins"] + r["opt_outs"] for r in rows)
        if total < rules["min_trend_events"]:
            add("low", "trend_thin", f"Only {total:,.0f} opt-in and opt-out events in the window: too few to read a trend. "
                "Consent may be kept outside Engagement (for example a shop platform's marketing flag on the customer).")
        else:
            run = 0
            for r in reversed(rows):
                if r["net"] < 0:
                    run += 1
                else:
                    break
            if run >= rules["net_negative_months"]:
                add("high", "list_shrinking", f"Opt-outs beat opt-ins in each of the last {run} months: the reachable list is shrinking.", months=run)
            for r in rows:
                others = [x["opt_outs"] for x in rows if x is not r]
                med = statistics.median(others) if others else 0
                if r["opt_outs"] >= rules["min_spike_optouts"] and med and r["opt_outs"] >= rules["optout_spike_ratio"] * med:
                    add("medium", "optout_spike", f"{r['month']}: {r['opt_outs']:,.0f} opt-outs, {r['opt_outs'] / med:.1f}x the usual month.", month=r["month"])

    categories = categories_note = None
    if a.consent_categories:
        settings = load(a.consent_categories)
        defined = [c for c in (settings.get("categories") if isinstance(settings, dict) else None) or [] if isinstance(c, dict)]
        if not defined:
            fail(f"{a.consent_categories}: no categories found; save the get_consent_settings response.")
        events = {}
        if a.consent_by_category:
            for raw, cells in crosstab(a.consent_by_category):
                if raw is None:
                    continue
                events[str(raw)] = events.get(str(raw), 0.0) + sum(cells.values())
        holders = {c: count_of(v, f"--holders {c}") for c, v in a.holders}
        categories = []
        for c in sorted(defined, key=lambda x: str(x.get("id"))):
            cid = str(c.get("id"))
            name = ((c.get("translations") or {}).get("") or {}).get("name") or cid
            ev = events.get(cid, 0.0) if a.consent_by_category else None
            held = holders.get(cid)
            li = bool(c.get("legitimate_interest"))
            if li:
                use = "legitimate interest"
            elif ev is None and held is None:
                use = "not measured"
            elif (ev or 0) > 0:
                use = "in use"
            elif held:
                use = "held, no changes in window"
            elif held == 0:
                use = "unused"
                add("medium", "category_unused", f"Consent category '{name}' is defined but nobody holds it and it had no consent events.", category=cid)
            else:
                use = "no events in window"
                add("low", "category_quiet", f"Consent category '{name}' had no consent events in the window; check whether anyone holds it.", category=cid)
            categories.append({"id": cid, "name": name, "legitimate_interest": li, "events": ev, "holders": held, "use": use})
        known = {c["id"] for c in categories}
        for cid in sorted(set(events) - known):
            if events[cid]:
                add("low", "category_undefined", f"Consent events use category '{cid}', which isn't defined in the consent settings.", category=cid)
        general = settings.get("general_consent") if isinstance(settings, dict) else None
        if isinstance(general, dict):
            free = sorted(k for k, v in general.items() if v is True)
            categories_note = (f"Channels that can send without a consent category (general_consent): {', '.join(free)}."
                               if free else "Every channel needs a consent category (general_consent is false for all).")

    findings.sort(key=lambda f: (PRIORITY[f["priority"]], f["kind"], f.get("channel") or f.get("category") or f.get("month") or ""))
    return {"ok": True, "base": base, "channels": channels, "any_reachable": any_reach,
            "any_reachable_share": share(any_reach, base), "high_value": high_value, "consent_trend": trend,
            "categories": categories, "categories_note": categories_note, "findings": findings,
            "summary": {p: sum(1 for f in findings if f["priority"] == p) for p in PRIORITY}}


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # category names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True, help="customers in the base: a number or a saved EQL count")
    ap.add_argument("--has-id", action="append", type=pair, default=[], help="CHANNEL=FILE_OR_NUMBER (repeat)")
    ap.add_argument("--reachable", action="append", type=pair, default=[], help="CHANNEL=FILE_OR_NUMBER (repeat)")
    ap.add_argument("--any-reachable", help="customers reachable on at least one channel")
    ap.add_argument("--high-value", help="high-value customers")
    ap.add_argument("--high-value-unreachable", help="high-value customers reachable on no measured channel")
    ap.add_argument("--consent-trend", help="EQL cross-tab: consent events by month and action")
    ap.add_argument("--consent-categories", help="saved get_consent_settings response")
    ap.add_argument("--consent-by-category", help="EQL cross-tab: consent events by category and action")
    ap.add_argument("--holders", action="append", type=pair, default=[], help="CATEGORY=FILE_OR_NUMBER (repeat)")
    ap.add_argument("--out", help="write the JSON here (a path in your working folder) instead of printing it")
    a = ap.parse_args()

    result = build(a, RULES)
    text = json.dumps(result, indent=1, ensure_ascii=False)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"{a.out}: can't write the file ({e.strerror or e}).")
        print(json.dumps({"ok": True, "out": a.out, "summary": result["summary"]}))
    else:
        print(text)


if __name__ == "__main__":
    main()
