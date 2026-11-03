#!/usr/bin/env python3
"""Turn campaign event counts into rates, period changes and flags.

Standard library only. No network access. Reads JSON from a file path
argument, or from stdin when no path is given, and prints Markdown.

Input format (counts are campaign event counts by status, as returned by
the EQL patterns in references/eql-campaign-metrics.md):

{
  "current":  {"<campaign or channel>": {"delivered": 1000, "clicked": 40, ...}, ...},
  "previous": {"<campaign or channel>": {"delivered": 900,  "clicked": 45, ...}, ...}
}

"previous" is optional. Status keys that are missing count as zero.
"unsubscribed" and "unsubscribe" are the same status, as are "hard_bounced" and
"hard_bounce", and "soft_bounced" and "soft_bounce" (projects spell them differently). Counts may be strings
("1,000"); a value that isn't a number counts as zero and is listed.

Usage:
    python3 summarise_campaign_counts.py counts.json
"""

import argparse
import json
import math
import sys

BOUNCE_KEYS = ("hard_bounce", "soft_bounce")
MIN_DELIVERED_TO_RANK = 500

THRESHOLDS = {
    "bounce_rate": (0.02, "High bounce"),
    "unsub_rate": (0.005, "High unsubscribe"),
    "complaint_rate": (0.001, "Spam complaints"),
    "failure_rate": (0.01, "Failed sends"),
}
SWING = 0.25
ALIASES = {"unsubscribed": "unsubscribe", "hard_bounced": "hard_bounce", "soft_bounced": "soft_bounce"}

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


def normalise(name, counts, problems):
    """Numbers per status, with status aliases merged."""
    out = {}
    for key, value in (counts or {}).items():
        v = num(value)
        if v is None:
            problems.append(f"{name}: {key} = {value!r} isn't a number; counted as 0")
            v = 0
        k = ALIASES.get(str(key).lower(), str(key).lower())
        out[k] = out.get(k, 0) + int(round(v))
    return out


def sends(c):
    for key in ("sent", "enqueued"):
        if c.get(key):
            return c[key]
    return c.get("delivered", 0) + sum(c.get(k, 0) for k in BOUNCE_KEYS) + c.get("failed", 0)


def ratio(num, den):
    return num / den if den else None


def metrics(c):
    s = sends(c)
    d = c.get("delivered", 0)
    return {
        "sends": s,
        "delivered": d,
        "delivery_rate": ratio(d, s),
        "bounce_rate": ratio(sum(c.get(k, 0) for k in BOUNCE_KEYS), s),
        "open_rate": ratio(c["opened"], d) if "opened" in c else None,
        "click_rate": ratio(c.get("clicked", 0), d),
        "unsub_rate": ratio(c.get("unsubscribe", 0), d),
        "complaint_rate": ratio(c.get("complained", 0), d),
        "failure_rate": ratio(c.get("failed", 0), s),
    }


def pct(x, digits=1):
    return "—" if x is None else f"{x * 100:.{digits}f}%"


def change(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / prev


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description="Turn campaign event counts into rates, period changes and flags "
                                 "(prints Markdown). Input format is in the script's docstring.")
    ap.add_argument("counts", nargs="?", help="JSON file of counts (read from stdin when left out)")
    args = ap.parse_args()
    if args.counts:
        with open(args.counts, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)
    for o in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(o, dict) and o.get("success") is False:
            sys.exit(f"{args.counts or 'stdin'}: Loomi Connect returned an error: {o.get('error') or 'no error text'}. "
                     "This check couldn't run; don't treat it as 'nothing found'.")
    problems = []
    current = {k: normalise(k, v, problems) for k, v in (data.get("current") or {}).items()}
    previous = {k: normalise(f"{k} (previous)", v, problems) for k, v in (data.get("previous") or {}).items()}

    rows, flags = [], []
    for name, counts in current.items():
        m = metrics(counts)
        p = metrics(previous[name]) if name in previous else None
        send_change = change(m["sends"], p["sends"]) if p else None
        click_change = change(m["click_rate"], p["click_rate"]) if p else None
        rows.append((name, m, send_change, click_change))

        for key, (limit, label) in THRESHOLDS.items():
            if m[key] is not None and m[key] > limit:
                flags.append(f"{label}: {name} at {pct(m[key], 2)} (threshold {pct(limit, 1)})")
        for label, delta in (("Send volume", send_change), ("Click rate", click_change)):
            if delta is not None and abs(delta) > SWING:
                flags.append(f"Big swing: {name} {label.lower()} {delta * 100:+.0f}% vs previous period")

    print("| Campaign | Sends | Delivered | Delivery % | Open %* | Click %* | Unsub % | Bounce % | Sends vs prev | Click % vs prev |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for name, m, sc, cc in sorted(rows, key=lambda r: -r[1]["sends"]):
        print(
            f"| {name} | {m['sends']:,} | {m['delivered']:,} | {pct(m['delivery_rate'])} | "
            f"{pct(m['open_rate'])} | {pct(m['click_rate'], 2)} | {pct(m['unsub_rate'], 2)} | "
            f"{pct(m['bounce_rate'], 2)} | {'—' if sc is None else f'{sc * 100:+.0f}%'} | "
            f"{'—' if cc is None else f'{cc * 100:+.0f}%'} |"
        )
    print("\n*Event-based rates: repeat opens and clicks count again.")

    rankable = [r for r in rows if r[1]["delivered"] >= MIN_DELIVERED_TO_RANK and r[1]["click_rate"] is not None]
    rankable.sort(key=lambda r: r[1]["click_rate"], reverse=True)
    if rankable:
        print("\n**Best by click rate:** " + "; ".join(f"{r[0]} ({pct(r[1]['click_rate'], 2)})" for r in rankable[:3]))
        worst = [r for r in rankable[3:]][-3:][::-1]
        if worst:
            print("**Worst by click rate:** " + "; ".join(f"{r[0]} ({pct(r[1]['click_rate'], 2)})" for r in worst))
    small = [r[0] for r in rows if r[1]["delivered"] < MIN_DELIVERED_TO_RANK]
    if small:
        print(f"**Not ranked (under {MIN_DELIVERED_TO_RANK} delivered):** " + ", ".join(small))

    print("\n**Flags:**")
    for f in flags or ["None above the thresholds."]:
        print(f"- {f}")
    for msg in problems:
        print(f"- Missing value: {msg}")


if __name__ == "__main__":
    main()
