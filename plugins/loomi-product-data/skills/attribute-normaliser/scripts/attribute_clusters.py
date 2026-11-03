#!/usr/bin/env python3
"""Cluster inconsistent values of the same attribute and propose a canonical value for each cluster.

Usage:
  python3 attribute_clusters.py [PRODUCTS ...] [--facets grid_facets.json ...] [--facet-attributes attrs.json]
         [--attributes colors,sizes,material] [--csv mapping.csv] [--out clusters.json]

  PRODUCTS            saved product pages (search_discovery_product_grid_insights, search_discovery_catalog_products,
                      Engagement search_catalog_items), or .jsonl with one product per line. Values are counted
                      once per product, including the product's inline variants (sku_color, sku_size).
  --facets            a saved product grid response with facets on (data.facet_counts.facets). Its value counts
                      cover the whole result set and win over product pages for the same attribute.
  --facet-attributes  a saved list_facet_attributes result: its facetable text attributes are checked too.
  --attributes        comma-separated attribute names to check (default: default_attributes in rules.json, plus
                      any from --facet-attributes).
  --csv               write the mapping file (attribute, value, canonical, products, confidence, review, reason):
                      one row per value to change. Cells that start with = + - @ are escaped.
  --out               also write the JSON result to this file.

How values are clustered, every step deterministic and named in each row's reason:
  1. fold: Unicode compatibility form, accents, case, punctuation and spacing (and word order, if sort_words);
  2. strip and expand: patterns such as a leading "100%" for materials, and the abbreviation and synonym table in
     references/value-synonyms.json ("nvy" -> navy, "navy blue" -> navy, "X-Large" -> xl);
  3. units: measurements ("32in", '32"', "81 cm", "8' x 10'") are converted to millimetres; equal ones merge (high
     confidence), and inches vs centimetres within unit_tolerance merge (medium);
  4. edit distance: remaining values at most max_edit_distance apart merge as low confidence, flagged for review.
     Values with different digits, short values and two known values (navy and black) never merge.
The proposed canonical value is the cluster's most-used spelling. It changes nothing in Bloomreach.

Rules: references/rules.json. Standard library only; no network access.
"""
import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from decimal import Decimal
from pathlib import Path

REFS = Path(__file__).resolve().parent.parent / "references"
RULES = json.loads((REFS / "rules.json").read_text(encoding="utf-8"))
TABLE = json.loads((REFS / "value-synonyms.json").read_text(encoding="utf-8"))
ACCOUNT_LIST = ("Loomi Connect returned an error about the account name; it isn't repeated because it can list "
                "other accounts. Ask the user to check the account name.")
NEVER = {"margin", "cost", "cost_price", "unit_cost", "profit", "wholesale_price", "landed_cost", "markup", "cost_per_unit"}
CONF_ORDER = ("high", "medium", "low")
UNITS = {"mm": Decimal(1), "cm": Decimal(10), "m": Decimal(1000), "in": Decimal("25.4"), "inch": Decimal("25.4"),
         "inches": Decimal("25.4"), '"': Decimal("25.4"), "″": Decimal("25.4"), "''": Decimal("25.4"),
         "”": Decimal("25.4"), "“": Decimal("25.4"), "ft": Decimal("304.8"), "feet": Decimal("304.8"),
         "foot": Decimal("304.8"), "'": Decimal("304.8"), "′": Decimal("304.8"), "’": Decimal("304.8")}
METRIC = {"mm", "cm", "m"}
UNIT_RE = "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True))
PART_RE = re.compile(r"\s*(\d+(?:\.\d+)?)\s*(" + UNIT_RE + r")?\s*")
SEP_RE = re.compile(r"\s*(?:x|×|by)\s*")


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def tool_error(err):
    text = str(err or "no error text")
    if re.search(r"account", text, re.I):  # these errors can list every account the user can access
        return ACCOUNT_LIST
    return text[:200]


def unwrap(data, path):
    while isinstance(data, dict):
        if data.get("success") is False:
            fail(f"{path}: {tool_error(data.get('error'))} This check couldn't run; don't treat it as 'nothing found'.")
        if "result" in data and isinstance(data["result"], (dict, list)):
            data = data["result"]
        elif "data" in data and isinstance(data["data"], (dict, list)):
            data = data["data"]
        else:
            break
    return data


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        fail(f"{path}: can't read it ({e.strerror or e}).")
    try:
        data = json.loads(text)
    except ValueError:
        start = text.find("{")  # some clients save a wrapper line before the JSON
        try:
            data = json.loads(text[start:]) if start >= 0 else None
        except ValueError as e:
            fail(f"{path}: can't read it as JSON ({e}).")
    return unwrap(data, path)


def flatten(rec):
    for key in ("attributes", "properties"):
        if isinstance(rec.get(key), dict):
            out = dict(rec[key])
            for k in ("id", "_id", "item_id", "pid"):
                if rec.get(k) not in (None, ""):
                    out.setdefault("pid", rec[k])
            return out
    return rec


def records_of(data):
    if isinstance(data, dict):
        resp = data.get("response")
        if isinstance(resp, dict) and isinstance(resp.get("docs"), list):
            return [d for d in resp["docs"] if isinstance(d, dict) and d.get("docType") != "content"]
        for key in ("items", "products", "docs"):
            if isinstance(data.get(key), list):
                return records_of(data[key])
        if isinstance(data.get("attributes"), dict) or isinstance(data.get("properties"), dict):
            return [flatten(data)]
        return []
    if isinstance(data, list):
        return [flatten(x) for x in data if isinstance(x, dict) and x.get("docType") != "content"]
    return []


def file_of(text):
    """FILE, or LABEL=FILE split on the first '=' (the label is ignored; a path that exists is never split)."""
    if os.path.exists(text):
        return text
    _, sep, path = text.partition("=")
    return path.strip() if sep and path.strip() else text


def iter_products(paths):
    for path in paths:
        if path.endswith(".jsonl"):
            try:
                with open(path, encoding="utf-8") as f:
                    lines = f.read().splitlines()
            except OSError as e:
                fail(f"{path}: can't read it ({e.strerror or e}).")
            for n, line in enumerate(lines, 1):
                if line.strip():
                    try:
                        obj = unwrap(json.loads(line), f"{path}:{n}")
                    except ValueError:
                        fail(f"{path}:{n}: malformed JSON line.")
                    yield from (records_of(obj) or ([flatten(obj)] if isinstance(obj, dict) else []))
        else:
            recs = records_of(load(path))
            if not recs:
                fail(f"{path}: no product records found; save a product grid page, catalog products or catalog items.")
            yield from recs


# ---------------------------------------------------------------------------------------------
# Folding

def kind_of(attr):
    a = attr.lower()
    for kind, names in sorted(RULES["attribute_kinds"].items()):
        if a in names:
            return kind
    return "generic"


def plain(s):
    """Unicode compatibility form, no accents, case-folded, trimmed."""
    s = unicodedata.normalize("NFKC", s)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return " ".join(s.casefold().split())


def punct(s):
    return " ".join(re.sub(r"[^\w\s]|_", " ", s).split())


def _table(kind):
    t = TABLE.get(kind) or TABLE["generic"]
    g = TABLE["generic"]
    words = {punct(plain(k)): punct(plain(v)) for k, v in {**g["words"], **t["words"]}.items()}
    values = {punct(plain(k)): punct(plain(v)) for k, v in {**g["values"], **t["values"]}.items()}
    known = {punct(plain(k)) for k in g["known"] + t["known"]} | set(values.values())
    strip = [re.compile(p) for p in g["strip"] + t["strip"]]
    return {"words": words, "values": values, "known": known, "strip": strip}


TABLES = {}


def table(kind):
    if kind not in TABLES:
        TABLES[kind] = _table(kind)
    return TABLES[kind]


def measurement(s):
    """Millimetre dimensions and unit systems for a value made only of measurements, else None."""
    parts = SEP_RE.split(s)
    nums = []
    for p in parts:
        m = PART_RE.fullmatch(p)
        if not m:
            return None
        nums.append([Decimal(m.group(1)), m.group(2)])
    if not any(u for _, u in nums):
        return None
    unit = None
    for item in reversed(nums):  # "8 x 10 ft": a bare number takes the next unit to its right
        if item[1]:
            unit = item[1]
        else:
            item[1] = unit
    for item in nums:
        if item[1] is None:
            item[1] = next(u for _, u in nums if u)
    mm = tuple((n * UNITS[u]).normalize() for n, u in nums)
    systems = frozenset("metric" if u in METRIC else "imperial" for _, u in nums)
    return mm, systems


def fold(value, kind):
    """(key, steps): the grouping key and the folding steps that changed the value."""
    t = table(kind)
    steps = []
    if " ".join(value.split()) != value:
        steps.append("spacing")
    nfkc = unicodedata.normalize("NFKC", value)
    bare = "".join(c for c in unicodedata.normalize("NFKD", nfkc) if not unicodedata.combining(c))
    if unicodedata.normalize("NFC", bare) != unicodedata.normalize("NFC", nfkc):
        steps.append("accents")
    if bare.casefold() != bare:
        steps.append("case")
    s = plain(value)
    meas = measurement(s)
    if meas:
        mm = meas[0]
        return ("m", mm), steps + ["units"]
    for rx in t["strip"]:
        m = rx.search(s)
        new = rx.sub("", s).strip()
        if m and new and new != s:
            steps.append("removed '" + m.group(0).strip() + "'")
            s = new
    p = punct(s)
    if p != s:
        steps.append("punctuation")
    words = []
    for w in p.split():
        x = t["words"].get(w, w)
        if x != w:
            steps.append("abbreviation or spelling")
        words.extend(x.split())
    s = " ".join(words)
    if s in t["values"]:
        if t["values"][s] != s:
            steps.append("synonym table")
        s = t["values"][s]
    elif RULES["sort_words"] and len(words) > 1:
        srt = " ".join(sorted(words))
        if srt in t["values"]:
            steps += ["word order", "synonym table"]
            s = t["values"][srt]
        elif srt != s:
            steps.append("word order")
            s = srt
    return ("v", s), sorted(set(steps))


def distance(a, b, cap):
    """Optimal string alignment distance (edits and neighbour swaps), or cap + 1 once it exceeds cap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > cap:
            return cap + 1
        prev2, prev = prev, cur
    return prev[-1]


def typo_distance(a, b):
    """Edit distance between two values that differ by a typo in one word, else None.

    The values must have the same words except one; that word must be long enough, start with the same letter
    and be within the edit cap for its length. So 'exmaple brand' matches 'example brand', but 'hooks' and
    'books', 'scented wax' and 'unscented wax', and 'wool' and 'wood' never do.
    """
    wa, wb = a.split(), b.split()
    if len(wa) != len(wb):
        return None
    diff = [(x, y) for x, y in zip(wa, wb) if x != y]
    if len(diff) != 1:
        return None
    x, y = diff[0]
    if min(len(x), len(y)) < RULES["min_length_for_edit"] or x[0] != y[0]:
        return None
    cap = RULES["max_edit_distance_long"] if min(len(x), len(y)) >= RULES["long_value_length"] \
        else RULES["max_edit_distance"]
    d = distance(x, y, cap)
    return d if d <= cap else None


# ---------------------------------------------------------------------------------------------
# Clustering one attribute

def cluster(attr, counts, pids):
    """Clusters (two or more distinct values) for one attribute, and a note if the edit pass was skipped."""
    kind = kind_of(attr)
    t = table(kind)
    by_key, steps = {}, {}
    for v in sorted(counts):
        key, st = fold(v, kind)
        by_key.setdefault(key, []).append(v)
        steps[v] = st
    key_count = {k: sum(counts[v] for v in vs) for k, vs in by_key.items()}
    order = sorted(by_key, key=lambda k: (-key_count[k], k[0], str(k[1])))
    parent, how = {}, {}
    roots = []
    note = None
    text_keys = [k for k in order if k[0] == "v"]
    do_edit = len(text_keys) <= RULES["max_values_for_edit"]
    if not do_edit:
        note = f"{attr}: {len(text_keys)} distinct values, over max_values_for_edit, so no edit-distance pass."
    tol = Decimal(str(RULES["unit_tolerance"]))
    for k in order:
        best = None
        for r in roots:
            if r[0] != k[0]:
                continue
            if k[0] == "m":
                a_mm, b_mm = k[1], r[1]
                if len(a_mm) != len(b_mm):
                    continue
                # only across unit systems, never inside one (100 cm and 99 cm stay apart)
                sys_a = measurement_systems(by_key[k])
                sys_b = measurement_systems(by_key[r])
                if sys_a == sys_b:
                    continue
                if all(abs(x - y) <= tol * max(x, y) for x, y in zip(a_mm, b_mm)):
                    cand = (0, r)
                    if best is None or cand < best:
                        best = cand
                        how[k] = "unit conversion within " + str((tol * 100).normalize()) + "%"
            elif do_edit:
                a, b = k[1], r[1]
                if a in t["known"] and b in t["known"]:
                    continue
                if re.findall(r"\d+", a) != re.findall(r"\d+", b):
                    continue
                if key_count[k] > Decimal(str(RULES["typo_max_share"])) * key_count[r]:
                    continue
                d = typo_distance(a, b)
                if d is not None and (best is None or (d, r) < best):
                    best = (d, r)
                    how[k] = f"edit distance {d}"
        if best is None:
            roots.append(k)
            how.pop(k, None)
        else:
            parent[k] = best[1]
    groups = {}
    for k in order:
        groups.setdefault(parent.get(k, k), []).append(k)
    out = []
    for root, keys in groups.items():
        values = [v for k in keys for v in by_key[k]]
        if len(values) < 2:
            continue
        canonical = sorted(values, key=lambda v: (-counts[v], len(v), v))[0]
        ck = next(k for k in keys if canonical in by_key[k])
        members = []
        for k in keys:
            for v in by_key[k]:
                if v == canonical:
                    continue
                reasons = (set(steps[v]) ^ set(steps[canonical])) - {"case", "units"}
                if style(v) != style(canonical):
                    reasons.add("case")
                link = None if k == ck else (how.get(k) or how.get(ck))
                if k[0] == "m" and link is None:
                    reasons.add("same measurement")
                confidence = "high"
                if link:
                    reasons.add(link)
                    confidence = "low" if link.startswith("edit") else "medium"
                members.append({"value": v, "products": counts[v], "confidence": confidence,
                                "review": confidence == "low",
                                "reason": ", ".join(sorted(reasons)) or "identical after folding",
                                **({"sample_pids": pids[v][:RULES["sample_pids"]]} if pids.get(v) else {})})
        members.sort(key=lambda m: (-m["products"], m["value"]))
        worst = max((m["confidence"] for m in members), key=CONF_ORDER.index)
        out.append({"canonical": canonical, "canonical_products": counts[canonical],
                    "products_to_change": sum(m["products"] for m in members), "confidence": worst,
                    "review": worst == "low", "members": members})
    out.sort(key=lambda c: (-c["products_to_change"], c["canonical"]))
    return out, note


def style(v):
    """lower, upper, title or mixed: two values in different styles differ in case."""
    letters = "".join(c for c in v if c.isalpha())
    if letters == letters.lower():
        return "lower"
    if letters == letters.upper():
        return "upper"
    return "title" if v.strip().istitle() else "mixed"


def measurement_systems(values):
    out = set()
    for v in values:
        m = measurement(plain(v))
        if m:
            out |= m[1]
    return frozenset(out)


# ---------------------------------------------------------------------------------------------

def csv_safe(v):
    """Stop spreadsheets running a cell as a formula: prefix =, +, -, @, tab or CR with '."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def split_values(v):
    if v is None or isinstance(v, (dict, bool)):
        return []
    items = v if isinstance(v, list) else [v]
    out = []
    for x in items:
        if x is None or isinstance(x, (dict, list, bool)):
            continue
        s = str(x)
        for sep in RULES["multi_value_separators"]:
            s = s.replace(sep, "\0")
        parts = s.split("\0")
        if len(parts) > 1:  # keep a single value as sent (trailing spaces are part of what needs fixing)
            parts = [x.strip() for x in parts]
        out += [x for x in parts if x.strip() and len(x) <= RULES["max_value_length"]]
    return out


def auto_attribute(name):
    if name.lower() in NEVER:
        return False
    words = re.split(r"[^a-z]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", name).lower())
    return not any(w in RULES["skip_attribute_words"] for w in words)


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # values can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("products", nargs="*", help="saved product pages or .jsonl files")
    ap.add_argument("--facets", action="append", default=[], help="a saved product grid response with facets on")
    ap.add_argument("--facet-attributes", help="a saved list_facet_attributes result")
    ap.add_argument("--attributes", help="comma-separated attribute names (default: rules.json default_attributes)")
    ap.add_argument("--csv", help="write the value-to-canonical mapping file")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    if not a.products and not a.facets:
        fail("Give at least one product file or --facets file.")

    if a.attributes:
        attrs = [x.strip() for x in a.attributes.split(",") if x.strip() and x.strip().lower() not in NEVER]
    else:
        attrs = list(RULES["default_attributes"])
        if a.facet_attributes:
            data = load(a.facet_attributes)
            rows = data if isinstance(data, list) else (data.get("attributes") if isinstance(data, dict) else None)
            if not isinstance(rows, list):
                fail(f"{a.facet_attributes}: no attribute list found; save the list_facet_attributes result.")
            for r in rows:
                if isinstance(r, dict) and r.get("facetable") is not False and r.get("type") == "STR" \
                        and r.get("name") and auto_attribute(str(r["name"])):
                    attrs.append(str(r["name"]))
    attrs = list(dict.fromkeys(attrs))
    wanted = set(attrs)

    counts = {x: {} for x in attrs}
    pids = {x: {} for x in attrs}
    source = {}
    facet_attrs = set()
    for path in a.facets:
        data = load(path)
        facets = ((data.get("facet_counts") or {}).get("facets") if isinstance(data, dict) else None)
        if not isinstance(facets, list):
            fail(f"{path}: no facet_counts.facets found; fetch the grid with facets on.")
        for fc in facets:
            name = fc.get("name") if isinstance(fc, dict) else None
            if name not in wanted or not isinstance(fc.get("value"), list):
                continue
            facet_attrs.add(name)
            source[name] = "facets"
            for item in fc["value"]:
                if not isinstance(item, dict) or "cat_id" in item:
                    continue
                n = item.get("count") if isinstance(item.get("count"), int) else 0
                for v in split_values(item.get("name")):
                    counts[name][v] = counts[name].get(v, 0) + n
    products = 0
    for rec in iter_products([file_of(p) for p in a.products]):
        products += 1
        pid = str(rec.get("pid") or rec.get("id") or rec.get("item_id") or rec.get("_id") or "")
        variants = [v for v in (rec.get("variants") or []) if isinstance(v, dict)]
        for attr in attrs:
            if attr in facet_attrs:
                continue
            seen = set(split_values(rec.get(attr)))
            for v in variants:
                seen |= set(split_values(v.get(attr)))
            if seen:
                source.setdefault(attr, "products")
            for v in seen:
                counts[attr][v] = counts[attr].get(v, 0) + 1
                if pid:
                    pids[attr].setdefault(v, []).append(pid)

    results, notes, rows = [], [], []
    for attr in attrs:
        if not counts[attr]:
            continue
        for v in pids[attr]:
            pids[attr][v] = sorted(set(pids[attr][v]))
        clusters, note = cluster(attr, counts[attr], pids[attr])
        if note:
            notes.append(note)
        for c in clusters:
            for m in c["members"]:
                rows.append([attr, m["value"], c["canonical"], m["products"], m["confidence"],
                             "yes" if m["review"] else "no", m["reason"]])
        cap = RULES["max_clusters_listed"]
        results.append({"attribute": attr, "kind": kind_of(attr), "source": source.get(attr),
                        "distinct_values": len(counts[attr]), "clusters": len(clusters),
                        "values_to_change": sum(len(c["members"]) for c in clusters),
                        "products_to_change": sum(c["products_to_change"] for c in clusters),
                        "low_confidence_clusters": sum(1 for c in clusters if c["review"]),
                        "top_clusters": clusters[:cap], "clusters_not_listed": max(0, len(clusters) - cap)})
    results.sort(key=lambda r: (-r["products_to_change"], r["attribute"]))
    missing = sorted(x for x in attrs if not counts[x])
    out = {"ok": True, "products_read": products, "facet_files": len(a.facets),
           "attributes_checked": len(results), "attributes_not_found": missing,
           "values_to_change": len(rows), "results": results, "notes": notes}
    if any(r["source"] == "facets" for r in results):
        notes.append("Facet counts can count variants (colour) rather than products, and list only the values the "
                     "facet returns; product counts from facets are approximate.")
    text = json.dumps(out, indent=2, ensure_ascii=False)
    try:
        if a.csv:
            with open(a.csv, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f, lineterminator="\n")
                w.writerow(["attribute", "value", "canonical", "products", "confidence", "review", "reason"])
                for r in rows:
                    w.writerow([csv_safe(x) for x in r])
        if a.out:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
    except OSError as e:
        fail(f"Can't write the output: {e.strerror or e}")
    print(text)


if __name__ == "__main__":
    main()
