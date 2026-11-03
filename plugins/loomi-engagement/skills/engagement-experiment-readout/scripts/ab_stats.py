#!/usr/bin/env python3
"""Significance maths for an Engagement A/B test readout.

Standard library only. No network access. It only reshapes aggregate counts
the assistant has already fetched (with EQL or a saved report).

Usage:
    python3 scripts/ab_stats.py counts.json
    python3 scripts/ab_stats.py --example        # print an example input file

Input JSON:
{
  "name": "Welcome flow subject line test",
  "metric": "conversion",              # conversion | click | revenue
  "control": "Control group",
  "days_run": 21,                      # whole days the test has been running
  "planned_days": 28,                  # optional: the duration decided up front
  "looks": 3,                          # optional: how many times results were checked
  "currency": "$",                     # optional, for revenue
  "aov_cv": 1.0,                       # optional: assumed order-value spread (sd / mean)
  "mde": 0.10,                         # optional: smallest relative lift worth finding
  "alpha": 0.05, "power": 0.8,         # optional
  "variants": [
    {"name": "Control group", "planned_share": 0.5, "n": 10400, "conversions": 312, "revenue": 24960},
    {"name": "Variant A",     "planned_share": 0.5, "n": 10310, "conversions": 361, "revenue": 28880}
  ],
  "periods": [                         # optional: per-week counts, to check novelty
    {"label": "week 1", "Control group": [3500, 98],  "Variant A": [3450, 140]},
    {"label": "week 2", "Control group": [3450, 106], "Variant A": [3430, 117]}
  ],
  "mixed": 140,                        # optional: customers found in more than one variant
  "mixed_excluded": true               # optional: true if the counts above already leave them out
}

"n" is unique customers assigned (or delivered, for email). "conversions" is
unique customers who converted (bought, or clicked for metric "click").
"revenue" is total revenue from those customers in the attribution window.
Numbers may be strings ("1000", "$1,234.00"). A variant with no customers or
no conversions count is listed but left out of the tests.
"""
import argparse
import json
import math
import random
import sys

EXAMPLE = {
    "name": "Example: welcome email subject line",
    "metric": "conversion",
    "control": "Control group",
    "days_run": 21,
    "planned_days": 28,
    "looks": 3,
    "currency": "$",
    "variants": [
        {"name": "Control group", "planned_share": 0.5, "n": 10400, "conversions": 312, "revenue": 24960},
        {"name": "Variant A", "planned_share": 0.5, "n": 10310, "conversions": 361, "revenue": 28880},
    ],
    "periods": [
        {"label": "week 1", "Control group": [3500, 98], "Variant A": [3450, 140]},
        {"label": "week 2", "Control group": [3450, 106], "Variant A": [3430, 117]},
        {"label": "week 3", "Control group": [3450, 108], "Variant A": [3430, 104]},
    ],
    "mixed": 140,
    "mixed_excluded": True,
}

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


def count(x):
    v = num(x)
    return None if v is None else int(round(v))


# ---------- distributions ----------

def norm_cdf(z):
    return 0.5 * math.erfc(-z / math.sqrt(2))


def norm_ppf(p):
    """Inverse normal CDF (Acklam's approximation, |error| < 1.2e-9)."""
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    lo, hi = 0.02425, 1 - 0.02425
    if p < lo:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > hi:
        return -norm_ppf(1 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def chi2_sf(x, k):
    """Upper tail of the chi-square distribution with k degrees of freedom."""
    if x <= 0:
        return 1.0
    s, z = k / 2.0, x / 2.0
    if z < s + 1:  # series for the lower incomplete gamma
        term = total = 1.0 / s
        n = s
        for _ in range(500):
            n += 1
            term *= z / n
            total += term
            if term < total * 1e-12:
                break
        lower = total * math.exp(-z + s * math.log(z) - math.lgamma(s))
        return max(0.0, 1 - lower)
    # continued fraction for the upper incomplete gamma
    b = z + 1 - s
    c = 1e300
    d = 1 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - s)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-12:
            break
    return math.exp(-z + s * math.log(z) - math.lgamma(s)) * h


# ---------- formatting ----------

def pct(x, digits=2):
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def signed_pct(x, digits=1):
    return "n/a" if x is None else f"{x * 100:+.{digits}f}%"


def money(x, cur):
    return "n/a" if x is None else f"{cur}{x:,.2f}"


# ---------- statistics ----------

def proportion_test(n1, c1, n2, c2, z_crit):
    """Control (1) vs variant (2) on a rate. Returns lift, CIs and p-value."""
    p1, p2 = c1 / n1, c2 / n2
    diff = p2 - p1
    se_unpooled = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    pooled = (c1 + c2) / (n1 + n2)
    se_pooled = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = diff / se_pooled if se_pooled > 0 else 0.0
    p_value = 2 * (1 - norm_cdf(abs(z)))
    rel = diff / p1 if p1 > 0 else None
    rel_ci = None
    if c1 > 0 and c2 > 0:
        # log of the risk ratio (delta method)
        se_log = math.sqrt((1 - p1) / c1 + (1 - p2) / c2)
        lr = math.log(p2 / p1)
        rel_ci = (math.exp(lr - z_crit * se_log) - 1, math.exp(lr + z_crit * se_log) - 1)
    return {
        "p1": p1, "p2": p2, "abs_diff": diff,
        "abs_ci": (diff - z_crit * se_unpooled, diff + z_crit * se_unpooled),
        "rel": rel, "rel_ci": rel_ci, "z": z, "p_value": p_value,
    }


def prob_beats_control(n1, c1, n2, c2, draws=20000, seed=7):
    """Bayesian chance the variant's rate beats the control's (Beta(1,1) priors)."""
    rng = random.Random(seed)
    wins = 0
    for _ in range(draws):
        if rng.betavariate(1 + c2, 1 + n2 - c2) > rng.betavariate(1 + c1, 1 + n1 - c1):
            wins += 1
    return wins / draws


def rpv_stats(n, conv, revenue, cv):
    """Revenue per customer and its variance, from aggregate counts.

    Per-customer revenue is 0 for non-buyers and ~order value for buyers. With
    no per-customer data, assume buyer revenue has sd = cv * mean.
    """
    if n <= 0:
        return None, None
    p = conv / n
    mean_buyer = revenue / conv if conv else 0.0
    second_moment = p * (mean_buyer ** 2) * (1 + cv ** 2)
    mean = revenue / n
    var = max(second_moment - mean ** 2, 0.0)
    return mean, var


def mean_test(m1, v1, n1, m2, v2, n2, z_crit):
    se = math.sqrt(v1 / n1 + v2 / n2)
    diff = m2 - m1
    z = diff / se if se > 0 else 0.0
    p_value = 2 * (1 - norm_cdf(abs(z)))
    rel = diff / m1 if m1 else None
    rel_ci = None
    if m1:
        rel_ci = ((diff - z_crit * se) / m1, (diff + z_crit * se) / m1)
    return {"abs_diff": diff, "abs_ci": (diff - z_crit * se, diff + z_crit * se),
            "rel": rel, "rel_ci": rel_ci, "z": z, "p_value": p_value, "se": se}


def n_per_arm_rate(p, rel_lift, alpha, power):
    if not p or not rel_lift:
        return None
    p2 = p * (1 + rel_lift)
    if not 0 < p2 < 1:
        return None
    za, zb = norm_ppf(1 - alpha / 2), norm_ppf(power)
    pbar = (p + p2) / 2
    num = (za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p * (1 - p) + p2 * (1 - p2))) ** 2
    return math.ceil(num / (p2 - p) ** 2)


def n_per_arm_mean(mean, var, rel_lift, alpha, power):
    if not mean or not rel_lift or var <= 0:
        return None
    za, zb = norm_ppf(1 - alpha / 2), norm_ppf(power)
    delta = mean * rel_lift
    return math.ceil(2 * var * (za + zb) ** 2 / delta ** 2)


# ---------- main ----------

def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(
        description="Significance maths for an Engagement A/B test readout (prints Markdown).",
        epilog="Run with --example to see the input format.")
    ap.add_argument("counts", nargs="?", help="JSON file of aggregate counts per variant")
    ap.add_argument("--example", action="store_true", help="print an example input file and exit")
    args = ap.parse_args()
    if args.example:
        print(json.dumps(EXAMPLE, indent=2))
        return
    if not args.counts:
        ap.error("give a counts JSON file, or --example")
    with open(args.counts, encoding="utf-8") as f:
        cfg = json.load(f)

    metric = cfg.get("metric", "conversion").lower()
    if metric not in ("conversion", "click", "revenue"):
        sys.exit("metric must be conversion, click or revenue")
    variants = []
    for v in cfg["variants"]:
        v = dict(v, n=count(v.get("n")), conversions=count(v.get("conversions")),
                 revenue=num(v.get("revenue")), planned_share=num(v.get("planned_share")))
        variants.append(v)
    names = [v["name"] for v in variants]
    control_name = cfg.get("control", names[0])
    if control_name not in names:
        sys.exit(f"Control {control_name!r} not in variants {names}")
    ctrl = next(v for v in variants if v["name"] == control_name)

    def problem(v):
        if not v["n"] or v["n"] < 0:
            return "no customers (n is 0 or missing)"
        if v["conversions"] is None:
            return "conversions missing"
        if v["conversions"] > v["n"]:
            return "more conversions than customers"
        if metric == "revenue" and v["revenue"] is None:
            return "revenue missing"
        return None

    skipped = [(v["name"], problem(v)) for v in variants if problem(v)]
    tests = [v for v in variants if v is not ctrl and not problem(v)]
    alpha = float(cfg.get("alpha", 0.05))
    power = float(cfg.get("power", 0.8))
    mde = float(cfg.get("mde", 0.10))
    cv = float(cfg.get("aov_cv", 1.0))
    cur = cfg.get("currency", "")
    days = count(cfg.get("days_run"))
    planned = count(cfg.get("planned_days"))
    looks = count(cfg.get("looks")) or 1

    # Multiple comparisons: Bonferroni across the test variants.
    k = max(len(tests), 1)
    alpha_adj = alpha / k
    z_crit = norm_ppf(1 - alpha_adj / 2)
    conf_label = f"{(1 - alpha_adj) * 100:.1f}%" if k > 1 else f"{(1 - alpha) * 100:.0f}%"

    title = cfg.get("name", "A/B test")
    print(f"## {title}: statistics ({metric})\n")

    # --- table ---
    def whole(x):
        return "n/a" if x is None else f"{x:,}"

    print("| Variant | Customers | Converted | Rate | Revenue | Revenue / customer |")
    print("|---|---|---|---|---|---|")
    for v in [ctrl] + [v for v in variants if v is not ctrl]:
        n, c, rev = v["n"], v["conversions"], v["revenue"]
        label = f"{v['name']} (control)" if v is ctrl else v["name"]
        print(f"| {label} | {whole(n)} | {whole(c)} | {pct(c / n if n and c is not None else None)} | "
              f"{money(rev, cur)} | {money(rev / n if rev is not None and n else None, cur)} |")
    if skipped:
        print()
    for name, why in skipped:
        print(f"- **{name}** is left out of the tests: {why}.")
    if problem(ctrl):
        print(f"\nThe control ({control_name}) can't be tested ({problem(ctrl)}), so no lift can be worked out. "
              "Fix the counts and run again.")
        sys.exit(1)

    # --- sample ratio mismatch ---
    total = sum(v["n"] or 0 for v in variants)
    shares = [v["planned_share"] for v in variants]
    print("\n### Traffic split check (sample ratio mismatch)")
    if all(s and v["n"] is not None for v, s in zip(variants, shares)) and total > 0:
        ssum = sum(shares)
        chi = sum((v["n"] - total * s / ssum) ** 2 / (total * s / ssum) for v, s in zip(variants, shares))
        p_srm = chi2_sf(chi, len(variants) - 1)
        actual = ", ".join(f"{v['name']} {v['n'] / total:.1%} (planned {s / ssum:.0%})" for v, s in zip(variants, shares))
        print(f"- Actual split: {actual}.")
        if p_srm < 0.001:
            print(f"- **Mismatch** (chi-square p = {p_srm:.2g}). Assignment or tracking may be broken; "
                  "don't trust the result until it's explained.")
        else:
            print(f"- No mismatch detected (chi-square p = {p_srm:.2g}).")
    else:
        print("- Planned shares or customer counts missing, so the split couldn't be checked.")
    mixed = count(cfg.get("mixed"))
    if mixed:
        share = mixed / max(total, 1)
        if cfg.get("mixed_excluded") is True:
            where = "The input says they are already left out of the counts above."
        else:
            where = ("**This script does not remove them**: if the counts above include them, count the "
                     "variants again without them (references/data-sources.md) before trusting the result.")
        print(f"- {mixed:,} customers appeared in more than one variant (profile merges), "
              f"{share:.1%} of assigned customers. {where}"
              + (" More than 5% are mixed, so the result is less reliable." if share > 0.05 else ""))

    # --- per variant tests ---
    verdicts = []
    print(f"\n### Lift against {control_name} ({conf_label} intervals"
          f"{', Bonferroni-adjusted for ' + str(k) + ' comparisons' if k > 1 else ''})")
    if not tests:
        print("- No variant has usable counts to compare with the control.")
    for v in tests:
        n1, c1, n2, c2 = ctrl["n"], ctrl["conversions"], v["n"], v["conversions"]
        if metric in ("conversion", "click"):
            r = proportion_test(n1, c1, n2, c2, z_crit)
            pb = prob_beats_control(n1, c1, n2, c2)
            rel_ci = r["rel_ci"]
            print(f"- **{v['name']}**: {pct(r['p1'])} → {pct(r['p2'])}, "
                  f"absolute {r['abs_diff'] * 100:+.2f} pts (CI {r['abs_ci'][0] * 100:+.2f} to {r['abs_ci'][1] * 100:+.2f}), "
                  f"relative {signed_pct(r['rel'])}"
                  + (f" (CI {signed_pct(rel_ci[0])} to {signed_pct(rel_ci[1])})" if rel_ci else "")
                  + (" (the control has no conversions, so there's no relative lift)" if r["rel"] is None else "")
                  + f"; p = {r['p_value']:.3g}; chance it beats control {pb:.0%}.")
            need = n_per_arm_rate(r["p1"], r["rel"], alpha_adj, power) if r["rel"] else None
            need_mde = n_per_arm_rate(r["p1"], mde, alpha_adj, power)
        else:
            m1, var1 = rpv_stats(n1, c1, ctrl["revenue"], cv)
            m2, var2 = rpv_stats(n2, c2, v["revenue"], cv)
            r = mean_test(m1, var1, n1, m2, var2, n2, z_crit)
            pb = norm_cdf(r["abs_diff"] / r["se"]) if r["se"] > 0 else 0.5
            rel_ci = r["rel_ci"]
            print(f"- **{v['name']}**: revenue per customer {money(m1, cur)} → {money(m2, cur)}, "
                  f"relative {signed_pct(r['rel'])}"
                  + (f" (CI {signed_pct(rel_ci[0])} to {signed_pct(rel_ci[1])})" if rel_ci else "")
                  + f"; p = {r['p_value']:.3g}; chance it beats control {pb:.0%} "
                  f"(assumes order-value sd = {cv:g} × mean).")
            need = n_per_arm_mean(m1, var1, r["rel"], alpha_adj, power) if r["rel"] else None
            need_mde = n_per_arm_mean(m1, var1, mde, alpha_adj, power)

        sig = r["p_value"] < alpha_adj
        have = min(n1, n2)
        rate_per_day = (have / days) if days else None
        remaining_days = None
        if need and need > have and rate_per_day:
            remaining_days = math.ceil((need - have) / rate_per_day)
        if need_mde:
            print(f"  - To detect a {mde:.0%} relative lift needs about {need_mde:,} customers per variant; "
                  f"it has {have:,} ({have / need_mde:.0%}).")
        if need and not sig:
            if remaining_days is not None:
                print(f"  - To confirm the observed {signed_pct(r['rel'])} would need about {need:,} per variant: "
                      + (f"roughly {remaining_days} more days at the current rate." if remaining_days <= 365
                       else "more than a year at the current rate."))
            elif need > have:
                print(f"  - To confirm the observed {signed_pct(r['rel'])} would need about {need:,} per variant.")
        verdicts.append((v["name"], sig, r["abs_diff"], r["rel"], rel_ci, remaining_days))

    # --- novelty / trend ---
    def period_rate(per, name):
        pair = per.get(name)
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            return None
        n, c = num(pair[0]), num(pair[1])
        return c / n if n and c is not None else None

    periods = cfg.get("periods") or []
    if len(periods) >= 2:
        print("\n### Lift by period (novelty check)")
        usable = []
        for per in periods:
            label = per.get("label", "?")
            cr = period_rate(per, control_name)
            if not cr:
                why = "no control counts" if control_name not in per else "the control rate is 0 or unreadable"
                print(f"- {label}: skipped ({why}).")
                continue
            usable.append((per, cr))
            parts = []
            for v in tests:
                vr = period_rate(per, v["name"])
                if vr is not None:
                    parts.append(f"{v['name']} {signed_pct(vr / cr - 1)}")
            print(f"- {label}: " + (", ".join(parts) or "n/a"))
        if len(usable) >= 2:
            (first, c_first), (last, c_last) = usable[0], usable[-1]
            for v in tests:
                v_first, v_last = period_rate(first, v["name"]), period_rate(last, v["name"])
                if v_first is None or v_last is None:
                    continue
                l1, l2 = v_first / c_first - 1, v_last / c_last - 1
                if l1 > 0 and l2 < l1 / 2:
                    print(f"- **{v['name']}: lift is fading** ({signed_pct(l1)} first period, {signed_pct(l2)} last). "
                          "Possible novelty effect; the long-run lift is likely nearer the later figure.")

    # --- duration and peeking ---
    print("\n### Has it run long enough?")
    if days is not None:
        if days < 7:
            print(f"- Only {days} days: less than one full week. Too early to call, whatever the p-value.")
        elif days % 7:
            print(f"- {days} days: not a whole number of weeks, so weekdays are unevenly represented.")
        else:
            print(f"- {days} days ({days // 7} whole weeks).")
    if planned and days is not None and days < planned:
        print(f"- Planned duration is {planned} days; {planned - days} days remain. "
              "Stopping early on a significant result inflates false positives.")
    if looks > 1 and not planned:
        print(f"- Results have been checked {looks} times with no planned end date. "
              "Treat only p < 0.01 (99%) as conclusive to allow for peeking.")

    # --- verdict ---
    print("\n### Statistical verdict")
    for name, sig, diff, rel, ci, rem in verdicts:
        lift = signed_pct(rel) if rel is not None else "the control had no conversions"
        if sig and diff > 0:
            print(f"- {name}: **significantly better** than control ({lift}).")
        elif sig and diff < 0:
            print(f"- {name}: **significantly worse** than control ({lift}).")
        elif rem is not None and rem <= 28:
            print(f"- {name}: **not yet significant**; about {rem} more days could settle it.")
        else:
            print(f"- {name}: **not significant**, and unlikely to become so in a reasonable time"
                  + (f" (the CI spans {signed_pct(ci[0])} to {signed_pct(ci[1])})." if ci else "."))
    for name, why in skipped:
        print(f"- {name}: **not tested** ({why}).")
    print("\nThese are frequentist tests on aggregate counts, with the assumptions above. "
          "Decide using the rules in references/statistics.md, not the p-value alone.")


if __name__ == "__main__":
    main()
