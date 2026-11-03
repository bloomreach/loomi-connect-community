#!/usr/bin/env python3
"""Compare Discovery categories with like-for-like peers.

Usage:
  python3 category_baseline.py [--categories list_categories.json] [--min-sessions 100]
                               [--threshold 25] table_page1.json [table_page2.json ...]

Each table file is the raw JSON returned by get_discovery_category_performance_table
(rows with visits, browse_sessions, conversion_rate, bounce_rate, ... and prev_* columns).
--categories is the raw JSON from list_categories; it supplies paths, so categories are
grouped by depth and same-named categories (e.g. men/pants vs women/pants) are told apart.

Peer groups:
  dynamic    - rule-based categories (IDs starting brg_dyn_), usually campaign or collection pages
  top-level  - first level of the category tree
  sub        - second level and below
  unknown    - IDs not found in list_categories (often tracking problems)

Prints JSON: per-group medians, outliers (a metric more than --threshold % from the group
median, among categories with at least --min-sessions browse sessions), big period swings,
new categories and tracking-hygiene rows. Standard library only; no network access.
"""
import argparse
import json
import math
import statistics
import sys

METRICS = {
    "conversion_rate": "higher",
    "bounce_rate": "lower",
    "rpv": "higher",
    "atc_rate": "higher",
    "ppv_per_visit": "higher",
}


def num(v):
    """A number from a Loomi Connect value ("$1,234.50", "12%", 7); None if missing or unreadable."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    for ch in "$£€,":
        s = s.replace(ch, "")
    s = s.strip()
    if s.endswith("%"):
        s = s[:-1].strip()
    if s.lower() in ("", "na", "n/a", "-", "—", "null"):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def check(doc, path):
    """Stop when Loomi Connect returned an error as data (success: false) instead of results."""
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            msg = (f"{path}: Loomi Connect returned an error: {d.get('error') or 'no error text'}. "
                   "This check couldn't run; don't treat it as 'nothing found'.")
            print(json.dumps({"ok": False, "error": msg}))
            sys.exit(1)
    return doc


def unwrap(data):
    while isinstance(data, dict) and "data" in data and not isinstance(data.get("rows"), list):
        if isinstance(data["data"], list):
            return data["data"]
        data = data["data"]
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        return unwrap(data["result"])
    return data


def load_rows(paths):
    rows = {}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            data = unwrap(check(json.load(f), p))
        for r in data.get("rows", []):
            rows[(r.get("cat_id"), r.get("category"))] = r
    return list(rows.values())


def load_categories(path):
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        data = unwrap(check(json.load(f), path))
    out = {}
    for c in data if isinstance(data, list) else []:
        cid = str(c.get("categoryId") or "").lower()
        if cid:
            out[cid] = c
    return out


def group_of(cat_id, cats):
    cid = str(cat_id or "").lower()
    if cid.startswith("brg_dyn_"):
        return "dynamic"
    c = cats.get(cid)
    if not c:
        return "unknown" if cats else "static"
    depth = len(c.get("extendedCategoryPath") or []) or str(c.get("categoryPaths", "")).count("/")
    return "top-level" if depth <= 1 else "sub"


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tables", nargs="+")
    ap.add_argument("--categories")
    ap.add_argument("--min-sessions", type=int, default=100)
    ap.add_argument("--threshold", type=float, default=25.0)
    a = ap.parse_args()

    cats = load_categories(a.categories)
    rows = load_rows(a.tables)
    names = {}
    hygiene, items = [], []
    for r in rows:
        cid, name = r.get("cat_id"), (r.get("category") or "").strip()
        sessions = num(r.get("browse_sessions")) or 0
        if not cid or cid == "(not set)" or not name or "://" in name or sessions == 0:
            hygiene.append({"cat_id": cid, "category": name, "browse_sessions": sessions,
                            "issue": "missing cat_id" if (not cid or cid == "(not set)") else
                                     "missing name" if not name else
                                     "URL sent as category name" if "://" in name else "no sessions"})
            continue
        c = cats.get(str(cid).lower())
        path = c.get("categoryPaths") if c else None
        visits = num(r.get("visits")) or 0
        item = {
            "cat_id": cid, "category": name, "path": path,
            "group": group_of(cid, cats), "browse_sessions": sessions,
            "revenue": num(r.get("revenue")),
            "conversion_rate": num(r.get("conversion_rate")),
            "bounce_rate": num(r.get("bounce_rate")),
            "rpv": num(r.get("rpv")), "atc_rate": num(r.get("atc_rate")), "aov": num(r.get("aov")),
            "ppv_per_visit": round((num(r.get("product_page_views")) or 0) / visits, 3) if visits else None,
            "change_revenue": num(r.get("change_revenue")),
            "prev_browse_sessions": num(r.get("prev_browse_sessions")),
        }
        items.append(item)
        names.setdefault(name.lower(), []).append(item)

    groups = {}
    for it in items:
        if it["browse_sessions"] >= a.min_sessions:
            groups.setdefault(it["group"], []).append(it)

    medians = {}
    for g, members in groups.items():
        medians[g] = {"count": len(members)}
        for m in METRICS:
            vals = [x[m] for x in members if x[m] is not None]
            medians[g][m] = round(statistics.median(vals), 3) if vals else None

    outliers = []
    for g, members in groups.items():
        if len(members) < 3:
            continue
        for it in members:
            flags = []
            for m, better in METRICS.items():
                base, v = medians[g].get(m), it[m]
                if not base or v is None:
                    continue
                diff = (v - base) / base * 100
                if abs(diff) >= a.threshold:
                    good = (diff > 0) == (better == "higher")
                    flags.append({"metric": m, "value": v, "peer_median": base,
                                  "diff_pct": round(diff, 1), "direction": "better" if good else "worse"})
            if flags:
                worse = [f for f in flags if f["direction"] == "worse"]
                outliers.append({**{k: it[k] for k in ("cat_id", "category", "path", "group", "browse_sessions", "revenue")},
                                 "verdict": ("mixed" if len(worse) < len(flags) else "underperforming") if worse else "outperforming",
                                 "flags": flags})
    order = {"underperforming": 0, "mixed": 1, "outperforming": 2}
    outliers.sort(key=lambda x: (order[x["verdict"]], -x["browse_sessions"]))

    swings = [{k: it[k] for k in ("cat_id", "category", "path", "browse_sessions", "change_revenue")}
              for it in items if it["change_revenue"] is not None and abs(it["change_revenue"]) >= 100]
    new = [{k: it[k] for k in ("cat_id", "category", "browse_sessions")}
           for it in items if not it["prev_browse_sessions"]]
    dup_names = {n: [{"cat_id": x["cat_id"], "path": x["path"]} for x in v] for n, v in names.items() if len(v) > 1}
    not_tracked = []
    if cats:
        seen = {str(it["cat_id"]).lower() for it in items}
        not_tracked = [{"cat_id": c.get("categoryId"), "path": c.get("categoryPaths")}
                       for cid, c in cats.items() if cid not in seen]

    json.dump({"min_sessions": a.min_sessions, "threshold_pct": a.threshold,
               "peer_medians": medians, "outliers": outliers, "period_swings": swings,
               "new_categories": new, "same_name_categories": dup_names,
               "in_tree_but_no_traffic": not_tracked, "tracking_hygiene": hygiene},
              sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
