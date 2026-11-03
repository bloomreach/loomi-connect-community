#!/usr/bin/env python3
"""Score how strongly products belong to a topic, from saved Loomi Connect
`search_discovery_product_grid_insights` responses, and compare candidate rules.

Usage:
  python3 score_association.py --terms "pickleball,pickle ball" [--exclude "tennis,padel"]
      [--weights weights.json] [--markdown] [--top 40]
      grid1.json grid2.json ...
      [--family "LABEL" family1.json ...] ...
      [--rule "LABEL" rule_page1.json rule_page2.json ...] ...

Wording files are the grid responses for the topic's searches (hybrid and standard
mode). The query and search mode are read from each response's debug URL; the URL
itself is never printed (it contains an auth key). Each file can be the full tool
envelope or just its `data` object.

--weights is a JSON object mapping each wording to its sessions, for example
{"pickleball": 4120, "pickle ball": 380}. Wordings missing from it get the floor weight.

--family starts a group of files holding one companion family's catalog probes (for
example "Court shoes": the grid for "court shoes" and "indoor court shoe"). Products
found only there get the tier "companion"; products also returned by the topic's own
searches are marked as backed by both knowledge and data. Every file after --family
belongs to it until the next --family, --rule or other option (so options such as
--top 5 can come after a group; wording files after such an option are wordings again).

--rule starts a group of files holding one candidate rule's products (its paged grid
responses, usually `query="*"` with the rule as fq). Every file after it belongs to
that rule until the next option.

Output: one JSON object (or Markdown with --markdown) with each product's score, tier,
evidence source (data, knowledge or both) and signals; for each family its size and
overlap with the topic's searches; and for each rule its size, precision, core recall, wrongly included and
missed products. Method: references/association-scoring.md.
Standard library only; no network access.
"""
import argparse
import json
import math
import re
import sys
from urllib.parse import parse_qs, urlsplit

FLOOR = 0.05
STANDARD_BONUS = 1.5


def check(doc, path):
    """Stop when Loomi Connect returned an error as data (success: false) instead of results."""
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            msg = (f"{path}: Loomi Connect returned an error: {d.get('error') or 'no error text'}. "
                   "This check couldn't run; don't treat it as 'nothing found'.")
            print(json.dumps({"ok": False, "error": msg}))
            sys.exit(1)
    return doc


def load(path):
    with open(path, encoding="utf-8") as f:
        data = check(json.load(f), path)
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]  # call_tool wraps the response once more
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    return data if isinstance(data, dict) else {}


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


def source(data):
    debug = data.get("debug") or {}
    params = parse_qs(urlsplit(debug.get("feUrl") or "").query, keep_blank_values=True)
    first = lambda k: (params.get(k) or [None])[0]
    try:
        start = int(first("start") or 0)
    except ValueError:
        start = 0
    return {
        "query": first("q"),
        "mode": (first("query.search_mode") or "hybrid").lower(),
        "start": start,
        "rewritten": bool(data.get("autoCorrectQuery") or data.get("relaxedQuery")),
        "redirected": bool(data.get("keywordRedirect")),
    }


def docs_of(data):
    response = data.get("response") or {}
    return response.get("docs") or [], response.get("numFound") or 0


def normalise(text):
    return re.sub(r"[\s\-_]+", "", (text or "").lower())


def matches(title, terms):
    low, flat = (title or "").lower(), normalise(title)
    return any(t.lower() in low or normalise(t) in flat for t in terms)


def split_args(argv):
    """Separate wording files from --family and --rule groups, which argparse can't express."""
    head, groups, current = [], {"--family": [], "--rule": []}, None
    i = 0
    while i < len(argv):
        if argv[i] in groups:
            if i + 1 >= len(argv):
                sys.exit(f"{argv[i]} needs a label")
            current = {"label": argv[i + 1], "files": []}
            groups[argv[i]].append(current)
            i += 2
            continue
        if argv[i].startswith("-") and argv[i] != "-":
            current = None  # any other option ends the group; its value goes to argparse with it
            head.append(argv[i])
        elif current is not None:
            current["files"].append(argv[i])
        else:
            head.append(argv[i])
        i += 1
    return head, groups["--family"], groups["--rule"]


def score(files, terms, exclude, weights):
    total = sum(weights.values()) or 0
    products, wordings, notes = {}, {}, []
    for path in files:
        data = load(path)
        src = source(data)
        query = src["query"] or path
        if src["redirected"] or src["rewritten"]:
            notes.append(f"{query} ({src['mode']}): rewritten or redirected; counted, but check it")
        share = max(weights.get(query, 0) / total, FLOOR) if total else 1.0
        docs, found = docs_of(data)
        wordings.setdefault(query, {"sessions": weights.get(query), "modes": {}})["modes"][src["mode"]] = found
        for rank, d in enumerate(docs, start=src["start"]):
            pid = str(d.get("pid") or "")
            if not pid:
                continue
            p = products.setdefault(pid, {"pid": pid, "title": d.get("title"), "brand": (d.get("brand") or "").strip(),
                                          "score": 0.0, "wordings": set(), "standard": False, "best_rank": rank})
            bonus = STANDARD_BONUS if src["mode"] == "standard" else 1.0
            p["score"] += share * bonus / math.log2(rank + 2)
            p["wordings"].add(query)
            p["standard"] |= src["mode"] == "standard"
            p["best_rank"] = min(p["best_rank"], rank)

    for p in products.values():
        p["title_match"] = matches(p["title"], terms)
        p["exclude_match"] = bool(exclude) and matches(p["title"], exclude)
        n = len(p["wordings"])
        if p["exclude_match"] and not p["title_match"]:
            p["tier"] = "off-topic"
        elif p["title_match"] or (p["standard"] and n >= 2):
            p["tier"] = "core"
        elif p["standard"] or n >= 2:
            p["tier"] = "likely"
        else:
            p["tier"] = "review"
        p["score"] = round(p["score"], 3)
        p["wordings"] = sorted(p["wordings"])
        p["families"], p["source"] = [], "data"
    ranked = sorted(products.values(), key=lambda p: -p["score"])
    return ranked, wordings, notes


def add_families(families, ranked, exclude):
    """Fold companion-family probes into the product list; return a summary per family."""
    by_pid = {p["pid"]: p for p in ranked}
    summaries = []
    for fam in families:
        found, pids = 0, []
        for path in fam["files"]:
            docs, n = docs_of(load(path))
            found = max(found, n)
            for d in docs:
                pid = str(d.get("pid") or "")
                if not pid or pid in pids:
                    continue
                pids.append(pid)
                p = by_pid.get(pid)
                if p is None:
                    p = {"pid": pid, "title": d.get("title"), "brand": (d.get("brand") or "").strip(), "score": 0.0,
                         "wordings": [], "standard": False, "best_rank": None, "title_match": False,
                         "exclude_match": bool(exclude) and matches(d.get("title"), exclude),
                         "tier": "companion", "families": [], "source": "knowledge"}
                    by_pid[pid] = p
                    ranked.append(p)
                elif p["source"] == "data":
                    p["source"] = "both"
                if fam["label"] not in p["families"]:
                    p["families"].append(fam["label"])
        both = [by_pid[x] for x in pids if by_pid[x]["source"] == "both"]
        summaries.append({
            "family": fam["label"],
            "numFound": found,
            "returned": len(pids),
            "in_topic_searches": len(both),
            "titles": [{"pid": x, "title": by_pid[x]["title"], "source": by_pid[x]["source"]} for x in pids[:15]],
        })
    return summaries


def compare(rule, by_pid):
    pids, titles, found = [], {}, 0
    for path in rule["files"]:
        docs, n = docs_of(load(path))
        found = max(found, n)
        for d in docs:
            pid = str(d.get("pid") or "")
            if pid and pid not in titles:
                pids.append(pid)
                titles[pid] = d.get("title")
    in_rule = set(pids)
    scored = [by_pid[p] for p in pids if p in by_pid]
    unscored = [titles[p] for p in pids if p not in by_pid]
    on_topic = [p for p in scored if p["tier"] in ("core", "likely", "companion")]
    core = [p for p in by_pid.values() if p["tier"] == "core"]
    core_in = [p for p in core if p["pid"] in in_rule]
    return {
        "rule": rule["label"],
        "numFound": found,
        "returned": len(pids),
        "partial": len(pids) < found,
        "scored": len(scored),
        "precision": round(len(on_topic) / len(scored), 2) if scored else None,
        "core_recall": round(len(core_in) / len(core), 2) if core else None,
        "wrongly_included": [p["title"] for p in scored if p["tier"] == "off-topic"],
        "review_included": [p["title"] for p in scored if p["tier"] == "review"][:10],
        "missed_core": [p["title"] for p in sorted(core, key=lambda p: -p["score"]) if p["pid"] not in in_rule][:10],
        "unscored_sample": unscored[:10],
        "unscored": len(unscored),
    }


def pct(x):
    return "n/a" if x is None else f"{round(x * 100)}%"


def markdown(out, top):
    lines = ["## Wordings", "", "| Wording | Sessions | Results (hybrid) | Results (standard) |", "|---|---|---|---|"]
    for q, w in out["wordings"].items():
        lines.append(f"| {q} | {w['sessions'] if w['sessions'] is not None else '-'} | "
                     f"{w['modes'].get('hybrid', '-')} | {w['modes'].get('standard', '-')} |")
    lines += ["", "## Tiers", "", ", ".join(f"{k}: {v}" for k, v in out["tiers"].items()), ""]
    lines += [f"## Products from the topic's searches (top {top})", "",
              "| # | pid | Title | Brand | Tier | Score | Wordings | Std | Families |", "|---|---|---|---|---|---|---|---|---|"]
    for i, p in enumerate([p for p in out["products"] if p["source"] != "knowledge"][:top], 1):
        title = (p["title"] or "").replace("|", "/")
        lines.append(f"| {i} | {p['pid']} | {title} | {p['brand']} | {p['tier']} | {p['score']} | "
                     f"{len(p['wordings'])} | {'yes' if p['standard'] else ''} | {', '.join(p['families'])} |")
    for f in out["families"]:
        lines += ["", f"## Family: {f['family']}", "",
                  f"- Catalog: {f['numFound']} products ({f['returned']} fetched); "
                  f"{f['in_topic_searches']} also returned by the topic's searches", ""]
        lines += [f"  - {t['pid']}: {(t['title'] or '')}{' (data and knowledge)' if t['source'] == 'both' else ''}"
                  for t in f["titles"]]
    for r in out["rules"]:
        lines += ["", f"## Rule: {r['rule']}", "",
                  f"- Size: {r['numFound']} ({r['returned']} fetched{', partial' if r['partial'] else ''}); "
                  f"scored {r['scored']}, unscored {r['unscored']}",
                  f"- Precision: {pct(r['precision'])}. Core recall: {pct(r['core_recall'])}",
                  f"- Wrongly included: {'; '.join(r['wrongly_included']) or 'none'}",
                  f"- Review-tier included: {'; '.join(r['review_included']) or 'none'}",
                  f"- Missed core: {'; '.join(r['missed_core']) or 'none'}",
                  f"- Unscored sample: {'; '.join(t or '' for t in r['unscored_sample']) or 'none'}"]
    for n in out["notes"]:
        lines.append(f"\nNote: {n}")
    return "\n".join(lines)


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    head, families, rules = split_args(sys.argv[1:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="saved grid responses for the topic's wordings")
    ap.add_argument("--terms", required=True, help="comma-separated topic terms for title matching")
    ap.add_argument("--exclude", default="", help="comma-separated neighbour-topic terms")
    ap.add_argument("--weights", help="JSON file mapping wording to sessions")
    ap.add_argument("--markdown", action="store_true", help="print Markdown instead of JSON")
    ap.add_argument("--top", type=int, default=40, help="products to show in Markdown (default 40)")
    a = ap.parse_args(head)

    split = lambda s: [t.strip() for t in s.split(",") if t.strip()]
    weights = {}
    if a.weights:
        with open(a.weights, encoding="utf-8") as f:
            weights = {str(k): num(v) or 0 for k, v in json.load(f).items()}
    try:
        ranked, wordings, notes = score(a.files, split(a.terms), split(a.exclude), weights)
        family_summaries = add_families(families, ranked, split(a.exclude))
        by_pid = {p["pid"]: p for p in ranked}
        compared = [compare(r, by_pid) for r in rules]
    except (OSError, ValueError) as e:
        print(json.dumps({"error": str(e)}))
        return 1

    tiers = {t: sum(p["tier"] == t for p in ranked) for t in ("core", "likely", "review", "off-topic", "companion")}
    out = {"wordings": wordings, "tiers": tiers, "products": ranked, "families": family_summaries,
           "rules": compared, "notes": notes}
    print(markdown(out, a.top) if a.markdown else json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
