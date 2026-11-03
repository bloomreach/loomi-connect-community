#!/usr/bin/env python3
"""Group search queries into collection themes by the attribute values their matching
products share, and add up the demand behind each theme.

Usage:
  python3 group_themes.py --baseline 56.89 --queries q1.json [q2.json] \
      --profiles profiles.jsonl [--min-shared 2] [--min-sessions 30] [--ignore brand]

  --queries   raw get_discovery_query_performance responses (current and prev_* columns)
  --profiles  output of scripts/preview_summary.py, one JSON line per query, run on a
              product grid call for that query (rows=1 is enough; leave facets on)
  --baseline  overall % change in search sessions for the same window, from
              get_discovery_search_performance (trends.browse_sessions)

Two queries join the same theme when their products share at least --min-shared
dominant facet values (for example category=/men/pants and colors=multi; a category
and its parent count once). Wording is not used. Themes are ranked by combined sessions. For each theme the output gives the
shared values (the starting point for a rule), combined sessions, change against the
baseline, revenue, a session-weighted conversion and bounce rate, and which member
queries are underserved (conversion under 75% of the top-20 median, or bounce over
1.5 times the median).

Queries without a profile are listed under `unprofiled` so you can fetch them.
Standard library only; no network access.
"""
import argparse
import json
import math
import statistics
import sys


def num(v):
    """A number from a tool value ("$1,000.00", "2.50%"), or None when missing or not a number."""
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


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def load_queries(paths):
    """Rows by query. Files from different windows (7 and 30 days) can't be mixed: the same
    query would have different numbers in each, and one would silently replace the other."""
    rows, origin = {}, {}
    for path in paths:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for d in (data, data.get("result") if isinstance(data, dict) else None):
            if isinstance(d, dict) and d.get("success") is False:
                fail(f"{path}: Loomi Connect returned an error: {d.get('error') or d.get('message') or 'no error text'}. "
                     "This check couldn't run; don't treat it as 'nothing found'.")
        if isinstance(data, dict) and isinstance(data.get("result"), dict) and "data" not in data:
            data = data["result"]
        for r in (data.get("data") or data).get("rows", []):
            q = r["query"].strip().lower()
            if q in rows:
                old = rows[q]
                if any(num(old.get(k)) != num(r.get(k)) for k in ("browse_sessions", "prev_browse_sessions")):
                    fail(f"query {r['query'].strip()!r} has different session counts in {origin[q]} and {path}: "
                         "these look like different windows (for example 7 and 30 days). Pass the query files "
                         "from one window only, the one that matches --baseline.")
            rows[q], origin[q] = r, path
    return rows


def load_profiles(paths):
    profiles = {}
    for path in paths:
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        items = [json.loads(line) for line in text.splitlines() if line.strip()] if not text.startswith("[") else json.loads(text)
        for p in items:
            q = ((p.get("source") or {}).get("query") or p.get("query") or "").strip().lower()
            if q:
                profiles[q] = p
    return profiles


def signature(profile, ignore):
    values = set()
    for d in profile.get("dominant") or []:
        value = d["value"] if isinstance(d, dict) else d
        if value.split("=", 1)[0] not in ignore:
            values.add(value)
    return values


def collapse(values):
    """Count a category and its parent as one shared value (keep the deepest path)."""
    cats = [v for v in values if v.startswith("category=")]
    drop = {c for c in cats for d in cats if d != c and d.startswith(c.rstrip("/") + "/")}
    return {v for v in values if v not in drop}


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queries", nargs="+", required=True)
    ap.add_argument("--profiles", nargs="+", required=True)
    ap.add_argument("--baseline", type=float, required=True)
    ap.add_argument("--min-shared", type=int, default=2)
    ap.add_argument("--min-sessions", type=int, default=30)
    ap.add_argument("--ignore", nargs="*", default=["brand"], help="facets not to group on (default: brand)")
    a = ap.parse_args()

    rows = load_queries(a.queries)
    profiles = load_profiles(a.profiles)
    growth = 1 + a.baseline / 100

    top = sorted(rows.values(), key=lambda r: r.get("browse_sessions") or 0, reverse=True)[:20]
    crs = [x for x in (num(r.get("conversion_rate")) for r in top) if x is not None]
    brs = [x for x in (num(r.get("bounce_rate")) for r in top) if x is not None]
    med_cr = statistics.median(crs) if crs else 0
    med_br = statistics.median(brs) if brs else 0
    missing = sorted(r["query"].strip() for r in rows.values()
                     if any(num(r.get(k)) is None for k in ("revenue", "conversion_rate", "bounce_rate")))

    names = [q for q, r in rows.items() if max(r.get("browse_sessions") or 0, r.get("prev_browse_sessions") or 0) >= a.min_sessions]
    sigs = {q: signature(profiles[q], set(a.ignore)) for q in names if q in profiles}

    # Union-find over queries that share enough dominant values.
    parent = {q: q for q in sigs}

    def find(q):
        while parent[q] != q:
            parent[q] = parent[parent[q]]
            q = parent[q]
        return q

    keys = list(sigs)
    for i, x in enumerate(keys):
        for y in keys[i + 1:]:
            if len(collapse(sigs[x] & sigs[y])) >= a.min_shared:
                parent[find(x)] = find(y)

    groups = {}
    for q in keys:
        groups.setdefault(find(q), []).append(q)

    themes = []
    for members in groups.values():
        sets = [sigs[q] for q in members]
        shared = set.intersection(*sets) if sets else set()
        common = sorted(v for v in set.union(*sets) if sum(v in s for s in sets) * 2 >= len(sets)) if sets else []
        cur = sum(rows[q].get("browse_sessions") or 0 for q in members)
        prev = sum(rows[q].get("prev_browse_sessions") or 0 for q in members)
        expected = prev * growth
        revenue = sum(num(rows[q].get("revenue")) or 0.0 for q in members)

        def weighted(key, members=members):
            """Session-weighted rate over the members that report it; None if none do."""
            pairs = [(num(rows[q].get(key)), rows[q].get("browse_sessions") or 0) for q in members]
            pairs = [(x, w) for x, w in pairs if x is not None]
            total = sum(w for _, w in pairs)
            return sum(x * w for x, w in pairs) / total if total else None

        cr, br = weighted("conversion_rate"), weighted("bounce_rate")
        underserved = []
        for q in members:
            r = rows[q]
            qcr, qbr = num(r.get("conversion_rate")), num(r.get("bounce_rate"))
            if (med_cr and qcr is not None and qcr < 0.75 * med_cr) or (med_br and qbr is not None and qbr > 1.5 * med_br):
                underserved.append({"query": r["query"], "sessions": r.get("browse_sessions"),
                                    "conversion_rate": r.get("conversion_rate"), "bounce_rate": r.get("bounce_rate")})
        themes.append({
            "queries": sorted(members, key=lambda q: -(rows[q].get("browse_sessions") or 0)),
            "shared_by_all": sorted(shared),
            "shared_by_most": common,
            "sessions": cur,
            "prev_sessions": prev,
            "vs_baseline_pct": round((cur / expected - 1) * 100, 1) if expected else None,
            "revenue": round(revenue, 2),
            "conversion_rate": round(cr, 2) if cr is not None else None,
            "bounce_rate": round(br, 2) if br is not None else None,
            "underserved": underserved,
        })
    themes.sort(key=lambda t: -t["sessions"])

    json.dump({
        "baseline_change_pct": a.baseline,
        "top20_median_conversion": med_cr,
        "top20_median_bounce": med_br,
        "themes": themes,
        "missing_values": {"queries": missing[:30], "note": "revenue, conversion or bounce missing (e.g. NA): "
                                                             "revenue counted as 0; rates left out of medians and averages"}
        if missing else None,
        "unprofiled": sorted((q for q in names if q not in profiles), key=lambda q: -(rows[q].get("browse_sessions") or 0))[:30],
    }, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
