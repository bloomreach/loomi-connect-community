#!/usr/bin/env python3
"""Turn Bloomreach Engagement funnel counts into leaks with revenue at stake.

Usage:
    python3 funnel_leaks.py funnel.json [--format markdown|json]

funnel.json (only "steps", "counts" and "aov" are required):
{
  "window": "last 30 days", "conversion_window": "7 days",
  "steps": ["Viewed a product", "Added to cart", "Purchased"],
  "counts": [28500, 4100, 1150],          # data.total.counts from the overall funnel
  "times": [-1, 420.5, 9800.0],           # optional: data.total.times (seconds)
  "aov": 82.0,                            # average order value
  "avg_cart_value": 95.0,                 # optional
  "purchasers_in_window": 1300,           # optional: one-step purchase funnel, for the identity check
  "recovery_rates": [null, 0.01, 0.05],   # optional, per step; defaults: 1% into cart, 5% into purchase
  "segments": {                           # optional: one funnel per value, same steps
    "device = iPhone": [9000, 900, 180],
    "device = Other": [19000, 3150, 960]
  },
  "min_customers": 100,                   # optional: below this, no value is given
  "cart_step": 1                          # optional: index of the cart step (default: the first
                                          # step named "cart" or "basket", else 1)
}

Abandoned carts = customers at the cart step minus customers at the next step.
Counts may be strings ("1,200"); a missing count is treated as 0 and said so.

Formulas are in references/revenue-at-stake.md. All values are estimates:
"walking away" is an upper bound; "recoverable" rests on the recovery rate.
Standard library only; no network access.
"""
import argparse
import json
import math
import sys

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


def counts_of(values, label, caveats):
    out = []
    for i, x in enumerate(values):
        v = num(x)
        if v is None:
            caveats.append(f"{label}: count {i + 1} is missing ({x!r}); treated as 0.")
        out.append(int(round(v or 0)))
    return out


def pct(x):
    return "—" if x is None else f"{x * 100:.1f}%"


def money(x):
    if x is None:
        return "—"
    if x >= 1000:
        return f"${x:,.0f}"
    return f"${x:,.2f}"


def default_rate(i, n_steps):
    return 0.05 if i == n_steps - 1 else 0.01


def cart_index(d, steps):
    last = len(steps) - 1
    if d.get("cart_step") is not None:
        i = int(d["cart_step"])
        if not 0 <= i < last:
            raise SystemExit(f"cart_step must be between 0 and {last - 1} (the last step is the purchase)")
        return i
    for i, name in enumerate(steps[:last]):
        if any(w in str(name).lower() for w in ("cart", "basket")):
            return i
    return min(1, last - 1)


def analyse(d):
    caveats = []
    steps, n = d["steps"], counts_of(d["counts"], "Funnel", caveats)
    if len(steps) != len(n) or len(n) < 2:
        raise SystemExit("steps and counts must be lists of the same length (2 or more)")
    aov = num(d.get("aov"))
    if aov is None:
        raise SystemExit("aov is missing or not a number: ask the user for their average order value")
    cart = num(d.get("avg_cart_value"))
    rates = [num(r) for r in (d.get("recovery_rates") or [])]
    min_n = int(num(d.get("min_customers")) or 100)
    times = [num(t) for t in (d.get("times") or [])]
    last = len(n) - 1
    ci = cart_index(d, steps)

    purchase_ok = True
    buyers = num(d.get("purchasers_in_window"))
    if buyers:
        share = n[last] / buyers if buyers else 0
        if share < 0.5:
            purchase_ok = False
            caveats.append(
                f"Only {share * 100:.0f}% of the {buyers:,.0f} purchasers in the window appear at the funnel's last step. "
                "Purchases are probably not linked to the browsing identity (server-side or imported orders), "
                "so the last step isn't a reliable leak. Check purchase tracking (engagement-tracking-health).")

    rows = []
    for i in range(1, len(n)):
        lost = max(n[i - 1] - n[i], 0)
        conv = n[i] / n[i - 1] if n[i - 1] else None
        into_last = i == last
        estimated = False
        if into_last:
            downstream = 1.0
        elif purchase_ok:
            downstream = n[last] / n[i] if n[i] else 0.0
        else:
            # The funnel's purchase step misses most buyers: use all purchasers in the window instead.
            downstream, estimated = (min(buyers / n[i], 1.0) if n[i] else 0.0), True
        value = min(aov, float(cart)) if (into_last and cart) else aov
        rate = rates[i] if i < len(rates) and rates[i] is not None else default_rate(i, len(n))
        assumed = not (i < len(rates) and rates[i] is not None)
        reliable = purchase_ok or not into_last
        enough = n[i - 1] >= min_n
        walk = lost * downstream * value if (reliable and enough) else None
        note = "" if reliable else "purchase step unreliable"
        if estimated:
            note = "onward conversion from all purchasers in the window (upper bound)"
        rows.append({
            "from": steps[i - 1], "to": steps[i], "customers": n[i], "step_conversion": conv, "lost": lost,
            "value_walking_away": walk, "recovery_rate": rate, "rate_assumed": assumed,
            "recoverable": walk * rate if walk is not None else None,
            "avg_seconds": times[i] if i < len(times) and times[i] not in (None, -1) else None,
            "note": note,
        })
        if not enough:
            rows[-1]["note"] = f"fewer than {min_n} customers"

    overall = n[last] / n[0] if n[0] else 0
    segs = []
    for name, counts in (d.get("segments") or {}).items():
        c = counts_of(counts, f"Segment {name}", caveats)
        conv = c[-1] / c[0] if c and c[0] else None
        step_convs = [(c[i] / c[i - 1]) if c[i - 1] else None for i in range(1, len(c))]
        gap = None
        if conv is not None and c[0] >= min_n and purchase_ok and conv < overall:
            gap = c[0] * (overall - conv) * aov
        segs.append({"segment": name, "entered": c[0], "end_to_end": conv, "step_conversions": step_convs,
                     "gap_value": gap})
    segs.sort(key=lambda s: -(s["gap_value"] or 0))

    weakest = max(rows, key=lambda r: r["recoverable"] or 0) if rows else None
    abandoned = None
    if purchase_ok or ci + 1 < last:
        left = max(n[ci] - n[ci + 1], 0)
        abandoned = {"cart_step": steps[ci], "next_step": steps[ci + 1], "customers": left,
                     "avg_cart_value": cart, "value_in_carts": left * cart if cart else None}
    return {"window": d.get("window"), "conversion_window": d.get("conversion_window"), "steps": steps,
            "counts": n, "overall_conversion": overall, "aov": aov, "rows": rows, "segments": segs,
            "abandoned_carts": abandoned, "biggest_leak": weakest, "caveats": caveats}


def render(r):
    out = []
    out.append(f"Funnel ({r.get('window') or 'window not given'}, conversion window "
               f"{r.get('conversion_window') or 'not given'}): overall conversion {pct(r['overall_conversion'])}, "
               f"AOV {money(r['aov'])}.\n")
    out.append("| Step | Customers | Step conversion | Lost | Value walking away | Recoverable (rate) | Avg time | Note |")
    out.append("|---|---|---|---|---|---|---|---|")
    out.append(f"| {r['steps'][0]} | {r['counts'][0]:,} | — | | | | | |")
    for row in r["rows"]:
        rate = f"{row['recovery_rate'] * 100:g}%{' assumed' if row['rate_assumed'] else ''}"
        t = f"{row['avg_seconds'] / 3600:.1f} h" if row["avg_seconds"] else ""
        out.append(f"| {row['to']} | {row['customers']:,} | {pct(row['step_conversion'])} | {row['lost']:,} | "
                   f"{money(row['value_walking_away'])} | {money(row['recoverable'])} ({rate}) | {t} | {row['note']} |")
    if r["segments"]:
        out.append("\n| Segment | Entered | End-to-end | Step conversions | Gap vs overall |")
        out.append("|---|---|---|---|---|")
        for s in r["segments"]:
            sc = " → ".join(pct(x) for x in s["step_conversions"])
            out.append(f"| {s['segment']} | {s['entered']:,} | {pct(s['end_to_end'])} | {sc} | {money(s['gap_value'])} |")
    a = r["abandoned_carts"]
    if a:
        out.append(f"\nAbandoned carts ({a['cart_step']}, not {a['next_step']}): {a['customers']:,} customers"
                   + (f", average cart {money(a['avg_cart_value'])}, about {money(a['value_in_carts'])} left in carts"
                      if a["value_in_carts"] else ""))
    b = r["biggest_leak"]
    if b:
        out.append(f"Biggest leak: {b['from']} → {b['to']} ({b['lost']:,} customers lost"
                   + (f", up to {money(b['value_walking_away'])}; about {money(b['recoverable'])} recoverable)"
                      if b["value_walking_away"] is not None else ")"))
    for c in r["caveats"]:
        out.append(f"Caveat: {c}")
    out.append("Values walking away are upper bounds; recoverable values depend on the recovery rate.")
    return "\n".join(out)


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("funnel")
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown")
    a = ap.parse_args()
    with open(a.funnel, encoding="utf-8") as f:
        d = json.load(f)
    r = analyse(d)
    if a.format == "json":
        json.dump(r, sys.stdout, indent=2)
        print()
    else:
        print(render(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
