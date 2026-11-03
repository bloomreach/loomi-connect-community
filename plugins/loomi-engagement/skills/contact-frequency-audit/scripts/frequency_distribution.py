#!/usr/bin/env python3
"""Turn saved per-threshold customer counts into a contact frequency distribution, fatigue signals and a cap.

Usage:
  python3 frequency_distribution.py --dir counts [--cap email=3] [--days 28] [--out frequency.json]
  python3 frequency_distribution.py --count email:all:1=e1.json --count email:all:2=e2.json ...
         [--count email:optout:1=o1.json ...] [--count email:engaged:1=c1.json ...]
         [--outcome-total email:optout=ot.json] [--base email=base.json] [--cap email=3]
         [--days 28] [--min-bucket-customers 200] [--out frequency.json]

--dir reads every file in a folder named <channel>_<metric>_<K>.json (for example email_all_4.json),
<channel>_optout_total.json and <channel>_base.json (channel names without underscores), the same as the
options below; other files are ignored. --count, --outcome-total and --base add to it.

Every FILE is a saved execute_analytics_eql result counting customers (`select count customers by <property>
grouping top 3 with null customers matching ...`); the script adds up every row, and an empty rows list is 0.
  --count CHANNEL:METRIC:K=FILE   customers who received at least K messages on CHANNEL in the window, and:
                                  METRIC all      nothing more
                                         optout   also unsubscribed or complained in the window
                                         engaged  also clicked in the window
  --outcome-total CHANNEL:METRIC=FILE   all customers with that outcome in the window, whatever they received
                                  (optional; checks how much of it the buckets explain)
  --base CHANNEL=FILE             the reachable base (for example customers with consent), for the share over the
                                  cap; default: recipients (customers with at least the lowest threshold)
  --cap CHANNEL=N                 a cap to test, in messages per week
  --days N                        window length in days (default from references/rules.json)

Buckets run from one threshold to just under the next; the last is open-ended. For each bucket: customers, share
of recipients, opt-out rate and engaged share (customers, not events). The first bucket with enough customers is
the reference; a later bucket is fatigued when its opt-out rate is much higher, or its engaged share falls. The
recommended cap is just under the first fatigued bucket, or the rule-of-thumb default when nothing is fatigued.
Thresholds are in references/rules.json. Maths uses exact fractions; only displayed values are rounded. Prints JSON
(or writes --out). Standard library only; no network access.
"""
import argparse
import json
import math
import re
import sys
from fractions import Fraction
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
MISSING = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}
METRICS = ("all", "optout", "engaged")
PRIORITY = {"high": 0, "medium": 1, "low": 2}
NAME = re.compile(r"^[a-z][a-z0-9_]*$")
DIR_COUNT = re.compile(r"^([a-z][a-z0-9]*)_(all|optout|engaged)_([1-9][0-9]*)\.json$")
DIR_TOTAL = re.compile(r"^([a-z][a-z0-9]*)_optout_total\.json$")
DIR_BASE = re.compile(r"^([a-z][a-z0-9]*)_base\.json$")


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


def customers(path):
    """The total of a saved customer-count EQL result: every row added up (null, "" and 'other' rows too)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {str(d.get('error') or 'no error text')[:200]} "
                 "This count couldn't be made; don't treat it as zero.")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    body = data.get("data") if isinstance(data, dict) else None
    if not isinstance(body, dict) or not isinstance(body.get("rows"), list):
        fail(f"{path}: no data.rows in the file. Pass the whole saved execute_analytics_eql result.")
    n = 0
    for r in body["rows"]:
        vals = r.get("values") if isinstance(r, dict) else None
        x = number(vals[0]) if isinstance(vals, list) and vals else None
        n += int(x) if x is not None and x > 0 else 0
    return n


def pct(x):
    return None if x is None else round(float(x * 100), 2)


def per_week(k, days):
    return Fraction(k * 7, days)


def show(fr):
    return round(float(fr), 2)


def count_arg(text):
    name, sep, path = text.partition("=")
    parts = name.split(":")
    if not sep or not path or len(parts) != 3 or not NAME.match(parts[0]) or parts[1] not in METRICS \
            or not parts[2].isdigit() or int(parts[2]) < 1:
        raise argparse.ArgumentTypeError(f"use CHANNEL:METRIC:K=FILE with METRIC all, optout or engaged and K a "
                                         f"whole number from 1; got {text!r}")
    return parts[0], parts[1], int(parts[2]), path


def pair_arg(text, what):
    name, sep, value = text.partition("=")
    if not sep or not value or not NAME.match(name.split(":")[0]):
        raise argparse.ArgumentTypeError(f"use {what}; got {text!r}")
    return name, value


def channel_report(channel, counts, outcome_totals, base, cap_week, days, rules):
    allc = counts.get("all", {})
    ks = sorted(allc)
    warnings = []
    for metric in ("optout", "engaged"):
        extra = sorted(set(counts.get(metric, {})) - set(ks))
        if extra:
            warnings.append(f"{metric} thresholds {extra} have no matching 'all' count and were ignored.")
    for a, b in zip(ks, ks[1:]):
        if allc[b] > allc[a]:
            warnings.append(f"customers with at least {b} ({allc[b]}) exceed those with at least {a} ({allc[a]}): "
                            "the counts probably cover different windows or filters. Buckets were clamped at 0.")
    recipients = allc[ks[0]]

    def bucket_value(metric, i):
        m = counts.get(metric, {})
        if ks[i] not in m:
            return None
        if i + 1 < len(ks):
            if ks[i + 1] not in m:
                return None
            return max(m[ks[i]] - m[ks[i + 1]], 0)
        return m[ks[i]]

    buckets = []
    for i, k in enumerate(ks):
        n = max(allc[k] - allc[ks[i + 1]], 0) if i + 1 < len(ks) else allc[k]
        hi = ks[i + 1] - 1 if i + 1 < len(ks) else None
        opt, eng = bucket_value("optout", i), bucket_value("engaged", i)
        opt_r = Fraction(opt, n) if opt is not None and n else None
        eng_r = Fraction(eng, n) if eng is not None and n else None
        if opt is not None and opt > n or eng is not None and eng > n:
            warnings.append(f"bucket {k}+: an outcome count exceeds the bucket's customers; check the queries match.")
        buckets.append({"from": k, "to": hi,
                        "label": f"{k}" if hi == k else (f"{k}-{hi}" if hi is not None else f"{k}+"),
                        "per_week": f"{show(per_week(k, days))}" + (
                            f"-{show(per_week(hi, days))}" if hi is not None and hi != k else ("+" if hi is None else "")),
                        "customers": n, "share_of_recipients_pct": pct(Fraction(n, recipients)) if recipients else None,
                        "optout": opt, "optout_rate_pct": pct(opt_r), "engaged": eng, "engaged_pct": pct(eng_r),
                        "judged": n >= rules["min_bucket_customers"], "fatigued": [], "_opt": opt_r, "_eng": eng_r})

    judged = [b for b in buckets if b["judged"]]
    ref = next((b for b in judged if b["_opt"] is not None), None)
    first_fatigued = None
    prev = None
    for b in judged:
        if ref is not None and b is not ref and b["_opt"] is not None:
            if b["_opt"] >= ref["_opt"] * Fraction(str(rules["fatigue_ratio"])) and \
                    b["_opt"] - ref["_opt"] >= Fraction(str(rules["fatigue_min_points"])) / 100:
                b["fatigued"].append("a higher opt-out rate")
        if prev is not None and prev["_eng"] is not None and b["_eng"] is not None and prev["_eng"] > 0 and \
                b["_eng"] <= prev["_eng"] * (1 - Fraction(str(rules["engagement_drop_ratio"]))):
            b["fatigued"].append("falling engagement")
        if b["_eng"] is not None:
            prev = b
        if b["fatigued"] and first_fatigued is None:
            first_fatigued = b

    denom, denom_name = (base, "base") if base else (recipients, "recipients")
    findings = []
    if first_fatigued is not None:
        cap_window = first_fatigued["from"] - 1
        over = allc[first_fatigued["from"]]
        cap = {"basis": "evidence", "per_window": cap_window, "per_week": show(per_week(cap_window, days)),
               "why": f"customers on {first_fatigued['label']} messages a window show {' and '.join(first_fatigued['fatigued'])}"}
        over_share = Fraction(over, denom) if denom else None
        priority = "high" if over_share is not None and over_share * 100 >= rules["share_high_pct"] else "medium"
        msg = (f"{channel}: from {first_fatigued['label']} messages per {days} days "
               f"({first_fatigued['per_week']} a week), {' and '.join(first_fatigued['fatigued'])}"
               + (f" (opt-out {first_fatigued['optout_rate_pct']}% vs {ref['optout_rate_pct']}% at {ref['label']})"
                  if ref is not None and first_fatigued["optout_rate_pct"] is not None else "")
               + f"; {over} customers ({pct(over_share)}% of {denom_name}) are at or above it")
        findings.append({"priority": priority, "kind": "fatigue", "message": msg})
    else:
        default = rules["default_caps_per_week"].get(channel)
        cap = {"basis": "rule_of_thumb" if default is not None else "none",
               "per_week": default, "per_window": None if default is None else show(Fraction(default) * days / 7),
               "why": ("no bucket with enough customers shows fatigue" if len(judged) >= 2
                       else "too few buckets with enough customers to judge")}
        findings.append({"priority": "low", "kind": "no_fatigue",
                         "message": f"{channel}: {cap['why']}; " + (
                             f"a rule-of-thumb cap of {default} a week is suggested" if default is not None
                             else "no default cap for this channel")})

    chosen = None
    if cap_week is not None:
        need = cap_week * days / 7
        k_over = math.floor(need) + 1  # more than the cap in the window
        measured = next((k for k in ks if k >= k_over), None)
        if measured is None:
            chosen = {"per_week": show(cap_week), "over_threshold": k_over, "customers_over": None, "share_pct": None,
                      "note": f"no count at {k_over}+ messages; the highest threshold measured is {ks[-1]}"}
        else:
            share = Fraction(allc[measured], denom) if denom else None
            chosen = {"per_week": show(cap_week), "over_threshold": measured, "customers_over": allc[measured],
                      "share_pct": pct(share), "of": denom_name,
                      "note": None if measured == k_over else
                      f"{k_over}+ wasn't measured; this is {measured}+, the nearest threshold above"}
            if share is not None and share * 100 >= rules["share_high_pct"]:
                findings.append({"priority": "high", "kind": "over_cap",
                                 "message": f"{channel}: {pct(share)}% of {denom_name} received {measured}+ messages in "
                                            f"{days} days, over the chosen cap of {show(cap_week)} a week"})

    if "optout" in outcome_totals and "optout" in counts and ks[0] in counts["optout"]:
        tot = outcome_totals["optout"]
        explained = counts["optout"][ks[0]]
        if tot and Fraction(explained, tot) * 100 < rules["coverage_min_pct"]:
            warnings.append(f"only {explained} of the {tot} customers who opted out in the window received {channel} "
                            "in it; per-bucket opt-out rates understate the problem (identity gaps, or opt-outs from "
                            "another source).")
    if "optout" not in counts:
        warnings.append("no opt-out counts: fatigue was judged on engagement only.")
    if "engaged" not in counts:
        warnings.append("no engaged counts: fatigue was judged on opt-outs only.")

    for b in buckets:
        del b["_opt"], b["_eng"]
    findings.sort(key=lambda f: PRIORITY[f["priority"]])
    return {"channel": channel, "window_days": days, "recipients": recipients, "base": base,
            "reference_bucket": ref["label"] if ref else None,
            "first_fatigued_bucket": first_fatigued["label"] if first_fatigued else None,
            "buckets": buckets, "recommended_cap": cap, "chosen_cap": chosen,
            "priority": findings[0]["priority"], "findings": findings, "warnings": sorted(set(warnings))}


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", help="a folder of saved results named <channel>_<metric>_<K>.json, "
                                  "<channel>_optout_total.json and <channel>_base.json")
    ap.add_argument("--count", action="append", type=count_arg, default=[], help="CHANNEL:METRIC:K=FILE: customers who received at least K (METRIC all, optout or engaged); repeatable")
    ap.add_argument("--outcome-total", action="append", default=[],
                    type=lambda t: pair_arg(t, "CHANNEL:optout=FILE"), help="CHANNEL:optout=FILE: everyone who opted out in the window, for the coverage check")
    ap.add_argument("--base", action="append", default=[], type=lambda t: pair_arg(t, "CHANNEL=FILE"),
                    help="CHANNEL=FILE: the reachable base (e.g. customers with consent); default recipients")
    ap.add_argument("--cap", action="append", default=[], type=lambda t: pair_arg(t, "CHANNEL=N (per week)"),
                    help="CHANNEL=N: a cap to test, in messages per week")
    ap.add_argument("--days", type=int, default=RULES["window_days"],
                    help=f"window length in days (default {RULES['window_days']}, from references/rules.json)")
    ap.add_argument("--min-bucket-customers", type=int, default=RULES["min_bucket_customers"],
                    help=f"buckets below this aren't judged (default {RULES['min_bucket_customers']}, from references/rules.json)")
    ap.add_argument("--out", help="write the JSON here (a path in your working folder) instead of printing it")
    a = ap.parse_args()
    if a.days < 1:
        fail("--days must be at least 1.")
    rules = {**RULES, "min_bucket_customers": a.min_bucket_customers}

    count_files, total_files, base_files = list(a.count), list(a.outcome_total), list(a.base)
    if a.dir:
        try:
            names = sorted(p.name for p in Path(a.dir).iterdir() if p.is_file())
        except OSError as e:
            fail(f"can't read the folder {a.dir} ({e}).")
        for n in names:
            path = str(Path(a.dir) / n)
            m = DIR_COUNT.match(n)
            if m:
                count_files.append((m.group(1), m.group(2), int(m.group(3)), path))
            elif DIR_TOTAL.match(n):
                total_files.append((DIR_TOTAL.match(n).group(1) + ":optout", path))
            elif DIR_BASE.match(n):
                base_files.append((DIR_BASE.match(n).group(1), path))
    if not count_files:
        fail("no counts: give --count CHANNEL:METRIC:K=FILE, or --dir with files named <channel>_<metric>_<K>.json.")

    counts = {}
    for channel, metric, k, path in count_files:
        slot = counts.setdefault(channel, {}).setdefault(metric, {})
        if k in slot:
            fail(f"{channel}:{metric}:{k} is given twice.")
        slot[k] = customers(path)
    totals = {}
    for name, path in total_files:
        channel, _, metric = name.partition(":")
        if metric != "optout":
            fail(f"--outcome-total takes CHANNEL:optout=FILE; got {name!r}.")
        totals.setdefault(channel, {})["optout"] = customers(path)
    bases = {name: customers(path) for name, path in base_files}
    caps = {}
    for name, value in a.cap:
        x = number(value)
        if x is None or x <= 0:
            fail(f"--cap {name}={value}: the cap must be a positive number of messages per week.")
        caps[name] = Fraction(str(x))

    for channel in sorted(set(totals) | set(bases) | set(caps)):
        if channel not in counts:
            fail(f"{channel} has no --count {channel}:all:<K> files.")
    reports = []
    for channel in sorted(counts):
        if not counts[channel].get("all"):
            fail(f"{channel}: give at least one {channel}:all:<K> count.")
        if counts[channel]["all"][min(counts[channel]["all"])] == 0:
            reports.append({"channel": channel, "window_days": a.days, "recipients": 0, "priority": "low",
                            "findings": [{"priority": "low", "kind": "no_data",
                                          "message": f"{channel}: nobody received a message in the window"}],
                            "buckets": [], "warnings": []})
            continue
        reports.append(channel_report(channel, counts[channel], totals.get(channel, {}), bases.get(channel),
                                      caps.get(channel), a.days, rules))
    reports.sort(key=lambda r: (PRIORITY[r["priority"]], r["channel"]))
    result = {"ok": True, "window_days": a.days, "channels": reports}
    text = json.dumps(result, indent=1, ensure_ascii=False)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"can't write {a.out} ({e}).")
        print(json.dumps({"ok": True, "out": a.out,
                          "channels": {r["channel"]: r["priority"] for r in reports}}))
    else:
        print(text)


if __name__ == "__main__":
    main()
