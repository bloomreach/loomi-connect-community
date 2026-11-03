#!/usr/bin/env python3
"""Measure the effect of one merchandising or marketing change with a
difference-in-differences (DiD) estimate and simple noise checks.

You give it totals for two equal-length windows (before and after the change,
change day excluded) for:
  * the TREATED thing: the query (and its variants), category, products or campaign
    the change affected;
  * one or more CONTROLS: something the change did not touch that shares the same
    site-wide trend (the search or category KPI card, or comparable untouched queries
    or categories).

It prints:
  * the raw before/after change for the treated thing and each control;
  * the DiD effect for visits, orders, revenue, conversion, revenue per visit and AOV,
    each with a 95% range: effect = (treated after / before) / (control after / before) - 1;
  * a two-proportion z-test on the treated conversion rate (before vs after), and a
    z-test on the DiD conversion effect;
  * the incremental revenue in the after window and per 30 days, with a range;
  * the smallest effect this much data could reliably detect;
  * minimum-data and window warnings, and a verdict:
    worked / no clear effect / made it worse / too early to tell.

Input: a JSON file (see --template). Counts can be numbers or money strings
such as "$6471.00". Field mapping:
  Discovery: visits = visits, orders = conversions, revenue = revenue.
  Campaigns: visits = delivered (or sent), orders = clicks (or purchases),
             revenue = attributed or UTM-tagged revenue if you have it, else 0.

The ranges are sampling noise only (Poisson orders, binomial conversion, and an
assumed order-value spread, `aov_cv`, default 1.0). Real day-to-day variation is
usually larger, so also run a placebo (the same calculation on two windows that
are both before the change) and pass it with --placebo.

Usage:
  python3 did_effect.py input.json [--placebo placebo.json] [--json]
  python3 did_effect.py --template [--out change.json]

Standard library only; no network access.
"""
import argparse
import json
import math
import sys

Z95 = 1.959964
Z_POWER80 = 0.841621  # one-sided 80% power
MIN_ORDERS = 30
MIN_VISITS = 300
MIN_DAYS = 7

TEMPLATE = {
    "change": "Category ranking rule 'Halloween Kids top rule' on kids tops (30100), started 30 Sep 22:00 UTC",
    "metric": "revenue",
    "days_before": 6,
    "days_after": 6,
    "window_before": "2026-09-24 to 2026-09-29",
    "window_after": "2026-10-01 to 2026-10-06",
    "aov_cv": 1.0,
    "treated": {"label": "kids tops (30100)",
                "before": {"visits": 1370, "orders": 157, "revenue": "$6964.00"},
                "after": {"visits": 1358, "orders": 144, "revenue": "$6471.00"}},
    "controls": [
        {"label": "all category pages, excluding treated", "subtract_treated": True,
         "before": {"visits": 63425, "orders": 20107, "revenue": "$2602615.00"},
         "after": {"visits": 62589, "orders": 19695, "revenue": "$2559335.00"}},
    ],
    "days_with_data_before": None,
    "days_with_data_after": None,
}

METRICS = ("visits", "orders", "revenue", "conversion", "rpv", "aov")
LABELS = {"visits": "Visits", "orders": "Orders", "revenue": "Revenue",
          "conversion": "Conversion rate", "rpv": "Revenue per visit", "aov": "Order value (AOV)"}


def num(v):
    """A number from a value ("$6,471.00", "12%"), or None when missing or not a number."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    s = str(v).strip().translate({ord(c): None for c in "$£€,"})
    if s.endswith("%"):
        s = s[:-1].strip()
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def cell(d, where, missing):
    """Counts for one window. A missing count is taken as 0 and noted in `missing`."""
    out = {}
    for k, v in (("visits", d.get("visits")), ("orders", d.get("orders", d.get("conversions"))),
                 ("revenue", d.get("revenue"))):
        x = num(v)
        if x is None:
            missing.append(f"{where} {k}")
        out[k] = x or 0.0
    return out


def derived(c):
    v, o, r = c["visits"], c["orders"], c["revenue"]
    return {"visits": v, "orders": o, "revenue": r,
            "conversion": o / v if v else None,
            "rpv": r / v if v else None,
            "aov": r / o if o else None}


def log_var(metric, c, cv2):
    """Approximate sampling variance of log(metric) for one window."""
    v, o = c["visits"], c["orders"]
    if v <= 0 or o <= 0:
        return None
    p = min(o / v, 0.999999)
    return {"visits": 1 / v,
            "orders": 1 / o,
            "revenue": (1 + cv2) / o,
            "conversion": (1 - p) / o,
            "rpv": (1 - p + cv2) / o,
            "aov": cv2 / o}[metric]


def pct(x):
    return None if x is None else round(x * 100, 2)


def norm_p(z):
    """Two-sided p-value for a standard normal z."""
    return math.erfc(abs(z) / math.sqrt(2))


def two_prop(o1, n1, o2, n2):
    if min(n1, n2) <= 0:
        return None
    p1, p2 = o1 / n1, o2 / n2
    pool = (o1 + o2) / (n1 + n2)
    se = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    z = (p2 - p1) / se
    se_u = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return {"before": round(p1 * 100, 3), "after": round(p2 * 100, 3),
            "change_pts": round((p2 - p1) * 100, 3),
            "change_pts_range": [round((p2 - p1 - Z95 * se_u) * 100, 3),
                                 round((p2 - p1 + Z95 * se_u) * 100, 3)],
            "z": round(z, 2), "p_value": round(norm_p(z), 4)}


def per_day(c, days):
    return {k: v / days for k, v in c.items()}


def did(treated, control, cv2, days_b, days_a):
    """Difference-in-differences for every metric, on a log (ratio) scale.

    Counts are put on a per-day basis first, so windows with different numbers of
    days with data still compare fairly. Rates (conversion, rpv, aov) don't depend
    on the day count.
    """
    tb, ta = derived(per_day(treated["before"], days_b)), derived(per_day(treated["after"], days_a))
    cb, ca = derived(per_day(control["before"], days_b)), derived(per_day(control["after"], days_a))
    out = {}
    for m in METRICS:
        vals = (tb[m], ta[m], cb[m], ca[m])
        if any(x is None or x <= 0 for x in vals):
            out[m] = None
            continue
        t_ratio, c_ratio = ta[m] / tb[m], ca[m] / cb[m]
        log_eff = math.log(t_ratio) - math.log(c_ratio)
        vs = [log_var(m, treated["before"], cv2), log_var(m, treated["after"], cv2),
              log_var(m, control["before"], cv2), log_var(m, control["after"], cv2)]
        if any(x is None for x in vs):
            out[m] = None
            continue
        se = math.sqrt(sum(vs))
        out[m] = {
            "treated_change_pct": pct(t_ratio - 1),
            "control_change_pct": pct(c_ratio - 1),
            "effect_pct": pct(math.exp(log_eff) - 1),
            "range_pct": [pct(math.exp(log_eff - Z95 * se) - 1), pct(math.exp(log_eff + Z95 * se) - 1)],
            "z": round(log_eff / se, 2) if se else None,
            "p_value": round(norm_p(log_eff / se), 4) if se else None,
            "detectable_pct": pct(math.exp((Z95 + Z_POWER80) * se) - 1),
            "_log": log_eff, "_se": se,
        }
    return out


def subtract(control, treated):
    out = {}
    for w in ("before", "after"):
        out[w] = {k: control[w][k] - treated[w][k] for k in ("visits", "orders", "revenue")}
    return out


def incremental_revenue(treated, effects, days_b, days_a):
    e = effects.get("revenue")
    if not e:
        return None
    actual = treated["after"]["revenue"]
    # What the treated revenue would have been without the change: actual / (1 + effect).
    lo, hi = e["_log"] - Z95 * e["_se"], e["_log"] + Z95 * e["_se"]
    cf = actual / math.exp(e["_log"])
    inc = actual - cf
    inc_lo = actual - actual / math.exp(lo)
    inc_hi = actual - actual / math.exp(hi)
    per30 = 30 / days_a
    return {"actual_after": round(actual, 2), "expected_without_change": round(cf, 2),
            "incremental_after_window": round(inc, 2),
            "incremental_range": [round(inc_lo, 2), round(inc_hi, 2)],
            "per_30_days": round(inc * per30, 2),
            "per_30_days_range": [round(inc_lo * per30, 2), round(inc_hi * per30, 2)]}


def warnings_for(spec, treated, missing=()):
    w = [f"No number for {m} (missing or not a number); counted as 0." for m in missing]
    db, da = spec["days_before"], spec["days_after"]
    if db != da:
        w.append(f"Windows differ in length ({db} vs {da} days). Use equal-length windows.")
    if da < MIN_DAYS:
        w.append(f"After window is {da} days (under {MIN_DAYS}). Weekday mix and one-off days can dominate.")
    if da % 7 or db % 7:
        w.append("Windows are not whole weeks, so the weekday mix may differ. Prefer 7, 14 or 28 days.")
    for when in ("before", "after"):
        c = treated[when]
        if c["orders"] < MIN_ORDERS:
            w.append(f"Only {int(c['orders'])} orders in the {when} window (under {MIN_ORDERS}). Treat rates as noisy.")
        if c["visits"] < MIN_VISITS:
            w.append(f"Only {int(c['visits'])} visits in the {when} window (under {MIN_VISITS}).")
    gb, ga = spec.get("days_with_data_before"), spec.get("days_with_data_after")
    if gb is not None and gb < db:
        w.append(f"The before window has {db - gb} day(s) with no data; counts were scaled per day with data.")
    if ga is not None and ga < da:
        w.append(f"The after window has {da - ga} day(s) with no data; counts were scaled per day with data.")
    return w


def placebo_fails(placebo, primary):
    """True when the pre-change placebo undermines the result."""
    lo, hi = placebo["range_pct"]
    return lo > 0 or hi < 0 or abs(placebo["effect_pct"]) >= abs(primary["effect_pct"])


def verdict(primary, too_little, controls_agree, placebo_hit):
    if primary is None:
        return "too early to tell", ("The treated item has no visits or orders in a window, so the change can't be measured. "
                                     "Check the wording or category shoppers actually use.")
    lo, hi = primary["range_pct"]
    if too_little and not (lo > 0 or hi < 0):
        return "too early to tell", "Not enough data yet to separate the change from noise."
    if lo > 0 or hi < 0:
        if not controls_agree:
            return "no clear effect", "The range excludes zero against one control but the controls disagree."
        if placebo_hit:
            return "no clear effect", "The pre-change placebo shows a drift as large as the effect, or the trends already diverged."
        if too_little:
            return ("worked" if lo > 0 else "made it worse"), "Statistically clear, but on thin data: confirm with more days or an A/B test."
        return ("worked" if lo > 0 else "made it worse"), "The range excludes zero against the control."
    return "no clear effect", f"The range includes zero; this data can only detect changes larger than about ±{primary['detectable_pct']}%."


def analyse(spec):
    cv2 = float(spec.get("aov_cv", 1.0)) ** 2
    db, da = int(spec["days_before"]), int(spec["days_after"])
    db_eff = int(spec.get("days_with_data_before") or db)
    da_eff = int(spec.get("days_with_data_after") or da)
    missing = []
    treated = {w: cell(spec["treated"][w], f"treated {w}", missing) for w in ("before", "after")}
    controls = []
    for c in spec.get("controls", []):
        ctl = {w: cell(c[w], f"control '{c.get('label', 'control')}' {w}", missing) for w in ("before", "after")}
        if c.get("subtract_treated"):
            ctl = subtract(ctl, treated)
        controls.append({"label": c.get("label", "control"), "data": ctl,
                         "effects": did(treated, ctl, cv2, db_eff, da_eff)})
    if not controls:
        raise SystemExit("Give at least one control: without one, a before/after change mixes the "
                         "effect of the change with the site-wide trend.")
    metric = spec.get("metric", "revenue")
    primary = controls[0]["effects"].get(metric)
    signs = {(c["effects"].get(metric) or {}).get("effect_pct", 0) > 0 for c in controls
             if c["effects"].get(metric)}
    controls_agree = len(signs) <= 1
    warns = warnings_for(spec, treated, missing)
    too_little = any(treated[w]["orders"] < MIN_ORDERS for w in treated) or da < MIN_DAYS
    return {"treated": treated, "controls": controls, "metric": metric, "primary": primary,
            "controls_agree": controls_agree, "too_little": too_little, "warnings": warns,
            "conversion_test": two_prop(treated["before"]["orders"], treated["before"]["visits"],
                                        treated["after"]["orders"], treated["after"]["visits"]),
            "incremental": incremental_revenue(treated, controls[0]["effects"], db_eff, da_eff),
            "days": (db, da)}


def money(x):
    if x is None:
        return "n/a"
    sign = "-" if x < 0 else "+"
    x = abs(x)
    if x >= 1e6:
        return f"{sign}${x / 1e6:.2f}M"
    if x >= 1e3:
        return f"{sign}${x / 1e3:.1f}k"
    return f"{sign}${x:,.0f}"


def fmt_pct(x):
    return "n/a" if x is None else f"{x:+.1f}%"


def print_text(spec, res, placebo_res):
    t = res["treated"]
    print(f"CHANGE: {spec.get('change', '(not given)')}")
    print(f"Windows: before {spec.get('window_before', '')} ({res['days'][0]} days) | "
          f"after {spec.get('window_after', '')} ({res['days'][1]} days); change day excluded")
    print()
    print(f"TREATED: {spec['treated'].get('label', 'treated')}")
    print(f"  {'':18} {'before':>12} {'after':>12}")
    for k in ("visits", "orders", "revenue"):
        print(f"  {k:18} {t['before'][k]:>12,.0f} {t['after'][k]:>12,.0f}")
    db, da = derived(t["before"]), derived(t["after"])
    print(f"  {'conversion':18} {db['conversion'] * 100 if db['conversion'] else 0:>11.2f}% "
          f"{da['conversion'] * 100 if da['conversion'] else 0:>11.2f}%")
    print()
    for c in res["controls"]:
        print(f"DIFFERENCE-IN-DIFFERENCES vs control: {c['label']}")
        print(f"  {'metric':20} {'treated':>9} {'control':>9} {'effect':>9}   95% range          p")
        for m in METRICS:
            e = c["effects"].get(m)
            if not e:
                print(f"  {LABELS[m]:20} n/a")
                continue
            lo, hi = e["range_pct"]
            print(f"  {LABELS[m]:20} {fmt_pct(e['treated_change_pct']):>9} {fmt_pct(e['control_change_pct']):>9} "
                  f"{fmt_pct(e['effect_pct']):>9}   {fmt_pct(lo):>7} to {fmt_pct(hi):<7}  {e['p_value']:.3f}")
        print()
    ct = res["conversion_test"]
    if ct:
        print("CONVERSION NOISE CHECK (treated, two-proportion z-test, before vs after)")
        print(f"  {ct['before']:.2f}% -> {ct['after']:.2f}% ({ct['change_pts']:+.2f} pts, range "
              f"{ct['change_pts_range'][0]:+.2f} to {ct['change_pts_range'][1]:+.2f}); z = {ct['z']}, p = {ct['p_value']}")
        print("  " + ("Conversion change is unlikely to be noise (p < 0.05)." if ct["p_value"] < 0.05
                      else "Conversion change is within normal noise (p >= 0.05)."))
        print()
    inc = res["incremental"]
    if inc:
        print("REVENUE IMPACT (vs first control)")
        print(f"  Expected without the change: ${inc['expected_without_change']:,.0f}; actual: ${inc['actual_after']:,.0f}")
        print(f"  Incremental in the after window: {money(inc['incremental_after_window'])} "
              f"(range {money(inc['incremental_range'][0])} to {money(inc['incremental_range'][1])})")
        print(f"  Per 30 days: {money(inc['per_30_days'])} "
              f"(range {money(inc['per_30_days_range'][0])} to {money(inc['per_30_days_range'][1])})")
        print()
    placebo_hit = False
    if placebo_res:
        p = placebo_res["primary"]
        pr = res["primary"]
        if p and pr:
            placebo_hit = placebo_fails(p, pr)
            print("PLACEBO (two windows both before the change; should show no effect)")
            print(f"  {LABELS.get(res['metric'], res['metric'])}: {fmt_pct(p['effect_pct'])} "
                  f"(range {fmt_pct(p['range_pct'][0])} to {fmt_pct(p['range_pct'][1])})")
            if p["range_pct"][0] > 0 or p["range_pct"][1] < 0:
                print("  The placebo shows an 'effect' with no change: treated and control were already "
                      "drifting apart. Pick a better control before trusting the result.")
            elif abs(p["effect_pct"]) >= abs(pr["effect_pct"]):
                print("  The placebo wobble is as large as the measured effect: treat the effect as noise.")
            else:
                print("  OK: the placebo shows no effect, and its wobble is smaller than the measured effect.")
            print()
    if res["warnings"] or not res["controls_agree"]:
        print("WARNINGS")
        for w in res["warnings"]:
            print(f"  - {w}")
        if not res["controls_agree"]:
            print("  - The controls disagree on the direction of the effect.")
        print()
    v, why = verdict(res["primary"], res["too_little"], res["controls_agree"], placebo_hit)
    pr = res["primary"]
    print(f"VERDICT: {v.upper()}")
    if pr:
        print(f"  {LABELS.get(res['metric'], res['metric'])} effect {fmt_pct(pr['effect_pct'])} "
              f"(95% range {fmt_pct(pr['range_pct'][0])} to {fmt_pct(pr['range_pct'][1])}). {why}")
    else:
        print(f"  {why}")
    print("  Ranges cover sampling noise only, not seasonality, promotions or other changes in the window.")
    return v


def clean(obj):
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [clean(x) for x in obj]
    return obj


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="JSON input file (see --template)")
    ap.add_argument("--placebo", help="JSON input for two pre-change windows (same format)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    ap.add_argument("--template", action="store_true", help="print an example input file and exit")
    ap.add_argument("--out", help="with --template: write the example to this file instead of printing it")
    a = ap.parse_args()
    if a.template:
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(json.dumps(TEMPLATE, indent=2) + "\n")
            print(f"Wrote an example input to {a.out}: replace its numbers with yours.")
        else:
            print(json.dumps(TEMPLATE, indent=2))
        return
    if a.out:
        ap.error("--out only works with --template")
    if not a.input:
        ap.error("give an input file, or --template")
    with open(a.input, encoding="utf-8") as f:
        spec = json.load(f)
    res = analyse(spec)
    placebo = None
    if a.placebo:
        with open(a.placebo, encoding="utf-8") as f:
            placebo = analyse(json.load(f))
    if a.json:
        placebo_hit = bool(placebo and placebo["primary"] and res["primary"]
                           and placebo_fails(placebo["primary"], res["primary"]))
        v, why = verdict(res["primary"], res["too_little"], res["controls_agree"], placebo_hit)
        out = clean({k: v_ for k, v_ in res.items()})
        out["verdict"], out["verdict_reason"] = v, why
        if placebo:
            out["placebo_primary"] = clean(placebo["primary"])
        print(json.dumps(out, indent=2))
    else:
        print_text(spec, res, placebo)


if __name__ == "__main__":
    sys.exit(main())
