#!/usr/bin/env python3
"""Show what each merchandising rule does to one Discovery search (or category page), and estimate its revenue effect.

Usage:
  python3 rule_impact.py --baseline base.json --toggled 900001=off_900001.json [--toggled all_algo=off_algo.json]
         [--toggled all=off_all.json] --query-perf query.json (--query-file query.txt | --query 'dress')
         [--product-rpv rpv_table.json] [--product-rpv P1=rpv-1.json ...] [--presence-check H1,H2=present.json]
         [--page-size 24] [--out impact.json]

Inputs are saved Loomi Connect results:
  --baseline        search_discovery_product_grid_insights with no rules disabled.
  --toggled         NAME=FILE, the same call with rules in disabled_customization_ids. NAME is the one rule ID
                    disabled, "all_algo" (every ranking algorithm rule disabled together) or "all" (every rule).
  --query-perf      get_discovery_query_performance (or get_discovery_category_performance_table); the row whose
                    query (or cat_id / category) equals the query exactly, ignoring case, is used.
  --query-file      a text file holding the query exactly as typed (one trailing newline is stripped). Use it for
                    any query that isn't only letters, digits, spaces and hyphens; --query is for those.
  --product-rpv     get_discovery_product_performance (one product; PID=FILE lets a not-found error count as
                    missing) or get_discovery_product_performance_table rows. Repeat as needed.
  --presence-check  optional, PIDS=FILE: the baseline call (rules on) with fq='pid:"A" OR pid:"B"' for the products
                    that appear only with a rule off; PIDS lists them, comma-separated. A listed product it doesn't
                    return is confirmed hidden by the rules. The file must hold every result (numFound fetched).

With no --toggled grids it lists the rules on the baseline and which grids to fetch (to_toggle).
For each toggled grid it reports what the rule(s) pin, boost or bury (merchandisingRulesApplied), the page-one
moves (position with the rule on vs off), the products it hides (numFound and pid differences), an estimated
revenue effect and a verdict (helps, neutral, hurts, hides sellers, no visible effect, unknown). The estimate is

  sum over moved products of (weight[position with rule] - weight[position without]) x product RPV x query visits

with the position-weight curve from references/rules.json (an assumption). Product RPV is across all of the
product's traffic, not this query. Products with no RPV are left out, never counted as 0. The grid's
`performance` score is an algorithm signal, not money, and is never used. Thresholds are in
references/rules.json. Standard library only; no network access; writes nothing to Bloomreach.
"""
import argparse
import json
import math
import re
import statistics
import sys
from decimal import Decimal
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
MISSING = {"", "na", "n/a", "-", "−", "—", "–", "null", "none", "nan"}
URL = re.compile(r"\b(?:https?|ftp)://\S+", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CONTEXT_ERROR = re.compile(r"project|organi[sz]ation|account|access|denied|forbidden|unauthori[sz]ed|\b40[13]\b|\b429\b", re.I)
NOT_FOUND = re.compile(r"not.?found|\b404\b|no such product|unknown product", re.I)


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def redact(text):
    return EMAIL.sub("[email removed]", URL.sub("[url removed]", str(text or "no error text")))[:200]


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


def dec(v):
    """An exact Decimal from a tool value (via its shortest text form), or None."""
    x = number(v)
    return None if x is None else Decimal(repr(x))


def money(d):
    return None if d is None else str(d.quantize(Decimal("0.01")))


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")


def error_of(doc):
    """The error text if the saved result is an error returned as data, else None."""
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            return str(d.get("error") or "no error text")
    return None


def unwrap(doc):
    while isinstance(doc, dict) and isinstance(doc.get("result"), (dict, list)):
        doc = doc["result"]
    while isinstance(doc, dict) and isinstance(doc.get("data"), (dict, list)):
        doc = doc["data"]
    return doc


def context_fail(path, err):
    if "account" in err.lower():  # these errors can list every account the user can access
        fail(f"{path}: Loomi Connect returned an error about the account; it isn't repeated because it can list "
             "other accounts. Stop and ask the user to check the account and their access.")
    fail(f"{path}: Loomi Connect returned an error: {redact(err)}. This stops the run; don't treat it as 'nothing found'.")


def load_grid(path):
    doc = read_json(path)
    err = error_of(doc)
    if err:
        context_fail(path, err)
    if isinstance(doc, dict) and isinstance(doc.get("result"), dict):
        doc = doc["result"]
    data = doc.get("data", doc) if isinstance(doc, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("response"), dict):
        fail(f"{path}: not a search_discovery_product_grid_insights result (no data.response).")
    return data


class Grid:
    def __init__(self, path):
        data = load_grid(path)
        resp = data["response"]
        debug = data.get("debug") or {}
        docs = resp.get("docs") or []
        # Banner rows (docType content, no pid) aren't products.
        self.docs = [d for d in docs if isinstance(d, dict) and d.get("docType") != "content" and d.get("pid") not in (None, "")]
        self.pos, self.title = {}, {}
        for d in self.docs:
            pid = str(d["pid"])
            if pid not in self.pos:
                self.pos[pid] = len(self.pos) + 1
                self.title[pid] = str(d.get("title") or "")[:80]
        nf = number(resp.get("numFound"))
        self.num_found = None if nf is None else int(nf)
        self.explain = debug.get("explain.structured") or {}
        self.rules = []
        for c in debug.get("customizations.explain") or []:
            if isinstance(c, dict) and c.get("id") not in (None, ""):
                self.rules.append({"id": str(c["id"]), "type": c.get("ruleType"), "live_in_test": bool(c.get("liveInTest"))})
        self.disabled_echo = sorted({str(x) for x in (debug.get("disabled_customizations.ids") or [])})

    @property
    def complete(self):
        """True when every result was fetched, so a pid missing here isn't in the results at all."""
        return self.num_found is not None and len(self.pos) >= self.num_found

    def merch(self, pid):
        entries = self.explain.get(pid) or []
        summary = next((e for e in reversed(entries) if isinstance(e, dict) and "totalNormalizedScore" in e), {})
        applied = summary.get("merchandisingRulesApplied") or {}
        return {str(k): sorted(map(str, v)) if isinstance(v, list) else [str(v)] for k, v in applied.items()} if isinstance(applied, dict) else {}


def merch_kind(key):
    k = key.lower()
    return "bury" if "bury" in k else "pin" if ("pin" in k or "slot" in k) else "boost"


def load_query_row(path, query):
    doc = read_json(path)
    err = error_of(doc)
    if err:
        context_fail(path, err)
    data = unwrap(doc)
    rows = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        fail(f"{path}: no rows in the query performance result.")
    q = query.strip().lower()
    for r in rows:
        if not isinstance(r, dict):
            continue
        if any(str(r.get(k) or "").strip().lower() == q for k in ("query", "cat_id", "category")):
            return r
    return None


def load_rpv(spec, rpv, currency, not_found):
    pid_hint, path = (spec.split("=", 1) if "=" in spec else (None, spec))
    doc = read_json(path)
    err = error_of(doc)
    if err:
        if pid_hint and NOT_FOUND.search(err) and not CONTEXT_ERROR.search(err):
            not_found.add(pid_hint.strip())
            return
        context_fail(path, err)
    data = unwrap(doc)
    rows = data.get("rows") if isinstance(data, dict) and "rows" in data else data
    rows = rows if isinstance(rows, list) else [rows]
    for r in rows:
        if not isinstance(r, dict):
            continue
        pid = r.get("productId", r.get("prod_id", r.get("pid")))
        if pid in (None, ""):
            continue
        value = dec(r.get("rpv"))
        if value is not None:
            rpv[str(pid)] = value
        if r.get("currency"):
            currency.add(str(r["currency"]))


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # titles can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", required=True, help="saved grid with no rules disabled")
    ap.add_argument("--toggled", action="append", default=[], help="NAME=FILE: grid with rule NAME disabled (a rule ID, all_algo or all); repeat")
    ap.add_argument("--query-perf", help="saved get_discovery_query_performance (or category performance table) result")
    ap.add_argument("--query", help="the search query (or category ID), only if it is letters, digits, spaces and hyphens")
    ap.add_argument("--query-file", help="a text file holding the search query (or category ID) exactly as typed")
    ap.add_argument("--product-rpv", action="append", default=[], help="saved product performance result, FILE or PID=FILE; repeat")
    ap.add_argument("--presence-check", action="append", default=[], help="PIDS=FILE: saved baseline grid filtered by fq to these comma-separated products; repeat")
    ap.add_argument("--page-size", type=int, default=RULES["page_size"], help="products on page one (default: rules.json page_size)")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    if a.page_size < 1:
        fail("--page-size must be at least 1.")
    if (a.query is None) == (a.query_file is None):
        fail("Give exactly one of --query and --query-file.")
    if a.query_file is not None:
        try:
            with open(a.query_file, encoding="utf-8", newline="") as f:
                a.query = f.read()
        except (OSError, UnicodeDecodeError) as e:
            fail(f"{a.query_file}: can't read the query ({e}).")
        if a.query.endswith("\r\n"):
            a.query = a.query[:-2]
        elif a.query.endswith("\n"):
            a.query = a.query[:-1]
    if not a.query.strip():
        fail("The query is empty.")

    base = Grid(a.baseline)
    toggled = []
    for spec in a.toggled:
        if "=" not in spec:
            fail(f"--toggled {spec!r}: expected NAME=FILE.")
        name, path = spec.split("=", 1)
        name = name.strip()
        if not name:
            fail(f"--toggled {spec!r}: the name is empty.")
        toggled.append((name, Grid(path)))
    names = [n for n, _ in toggled]
    if len(set(names)) != len(names):
        fail("Each --toggled name may appear only once.")

    rpv, currency, rpv_not_found = {}, set(), set()
    for spec in a.product_rpv:
        load_rpv(spec, rpv, currency, rpv_not_found)
    present, checked = set(), set()
    for spec in a.presence_check:
        if "=" not in spec:
            fail(f"--presence-check {spec!r}: expected PIDS=FILE (the comma-separated product IDs the fq asked for).")
        pids, path = spec.split("=", 1)
        pids = {p.strip() for p in pids.split(",") if p.strip()}
        if not pids:
            fail(f"--presence-check {spec!r}: no product IDs before '='.")
        grid = Grid(path)
        if not grid.complete:
            fail(f"{path}: the presence check holds {len(grid.pos)} of {grid.num_found} results; fetch it with rows "
                 "at least the number of products asked for.")
        checked |= pids
        present |= set(grid.pos)

    warnings, not_checked = [], []
    if a.page_size > len(RULES["position_weights"]):
        warnings.append(f"page_size ({a.page_size}) is longer than position_weights ({len(RULES['position_weights'])} "
                        "positions): products below the end of the curve weigh 0.")
    row = load_query_row(a.query_perf, a.query) if a.query_perf else None
    if a.query_perf and row is None:
        not_checked.append(f"No row in the query performance file matches {a.query!r} exactly, so there's no revenue estimate "
                           "(`search` is a substring match: fetch the page that holds the exact query).")
    if not a.query_perf:
        not_checked.append("No query performance file was given, so there's no revenue estimate.")
    visits = dec(row.get("visits")) if row else None
    q_revenue = dec(row.get("revenue")) if row else None
    q_rpv = dec(row.get("rpv")) if row else None
    views = dec(row.get("product_page_views")) if row else None
    if q_revenue is None and visits is not None and q_rpv is not None:
        q_revenue = visits * q_rpv
    if row is not None and not visits:
        not_checked.append("The query's row has no visits, so there's no revenue estimate.")
        visits = None
    elif row is not None and not q_revenue:
        not_checked.append("The query's row has no revenue, so the effect can't be set against it and the verdicts are unknown.")
    if row is not None and row.get("currency"):
        currency.add(str(row["currency"]))
    mixed_currency = len(currency) > 1
    if mixed_currency:
        warnings.append("The RPV files and query row are in different currencies (" + ", ".join(sorted(currency))
                        + "); no estimates or RPV comparisons are made. Fetch them all for one site.")
    if visits is not None and visits < RULES["min_query_visits"]:
        warnings.append("Low traffic: fewer than min_query_visits visits in the period, so the estimates are fragile.")

    # Position weights (an assumption), optionally scaled to the query's product views per visit.
    curve = [Decimal(str(w)) for w in RULES["position_weights"]][:a.page_size]
    scale = Decimal(1)
    scale_note = "It is used unscaled."
    if RULES["scale_weights_to_query_views"] and views is not None and visits and sum(curve):
        scale = (views / visits) / sum(curve)
        scale_note = ("Its page-one total is scaled to this query's product views per visit "
                      f"({money(views / visits)}), so only its shape is assumed.")

    def weight(pos):
        return curve[pos - 1] * scale if pos is not None and pos <= len(curve) else Decimal(0)

    page = [p for p, i in sorted(base.pos.items(), key=lambda x: x[1]) if i <= a.page_size]
    page_rpvs = sorted(rpv[p] for p in page if p in rpv)
    median_rpv = statistics.median(page_rpvs) if page_rpvs and not mixed_currency else None

    base_ids = {r["id"]: r for r in base.rules}
    ranking_ids = sorted(i for i, r in base_ids.items() if r["type"] in RULES["ranking_rule_types"])
    algo_ids = sorted(i for i, r in base_ids.items() if r["type"] in RULES["algo_rule_types"])

    results = []
    for name, off in toggled:
        if name == "all_algo":
            expected, label = set(algo_ids), "all ranking algorithm rules together"
        elif name == "all":
            expected, label = set(base_ids), "every rule"
        else:
            expected, label = {name}, f"rule {name}"
            if name not in base_ids:
                warnings.append(f"Rule {name} isn't in the baseline grid's customizations.explain; check the ID.")
        r_warn = []
        missing_echo = sorted(expected - set(off.disabled_echo))
        if missing_echo:
            r_warn.append("The grid doesn't confirm these rules were disabled (not in disabled_customizations.ids): "
                          + ", ".join(missing_echo))
        if any(base_ids.get(i, {}).get("live_in_test") for i in expected):
            r_warn.append("A rule here is live in an A/B test, so shoppers in the other bucket see a different page.")
        extra_rules = sorted(({"id": r["id"], "type": r["type"]} for r in off.rules if r["id"] not in base_ids),
                             key=lambda r: r["id"])

        # What the rule(s) apply: merchandising effects present with them on and gone or changed with them off.
        applied = []
        for pid in sorted(base.pos, key=lambda p: base.pos[p]):
            on_m = base.merch(pid)
            if on_m and on_m != off.merch(pid):
                kinds = sorted({merch_kind(k) for k in on_m})
                applied.append({"pid": pid, "title": base.title.get(pid), "kinds": kinds, "applied": on_m,
                                "position": base.pos[pid], "rpv": money(rpv.get(pid))})

        # Hidden products: in the results only with the rule(s) off.
        hidden_count = None
        if base.num_found is not None and off.num_found is not None:
            hidden_count = max(0, int(off.num_found - base.num_found))
        hidden = []
        for pid in sorted((p for p in off.pos if p not in base.pos), key=lambda p: off.pos[p]):
            if pid in checked and pid in present:
                continue  # it's in the results with the rules on, just deeper than the page fetched
            if base.complete or pid in checked:
                status = "confirmed"
            else:
                status = "not_confirmed"
            hidden.append({"pid": pid, "title": off.title.get(pid), "position_without": off.pos[pid],
                           "status": status, "rpv": money(rpv.get(pid))})
        hidden_pids = {h["pid"] for h in hidden}

        # Page-one moves: position with the rule(s) on vs off.
        moves = []
        for pid in sorted(set(base.pos) | set(off.pos)):
            on, offp = base.pos.get(pid), off.pos.get(pid)
            on_page = on if on is not None and on <= a.page_size else None
            off_page = offp if offp is not None and offp <= a.page_size else None
            if on_page is None and off_page is None or on_page == off_page:
                continue
            moves.append({"pid": pid, "title": base.title.get(pid) or off.title.get(pid),
                          "with_rule": on_page, "without_rule": off_page,
                          "hidden": pid in hidden_pids,
                          "weight_change": weight(on_page) - weight(off_page), "rpv": rpv.get(pid)})
        moves.sort(key=lambda m: (m["with_rule"] or 10 ** 6, m["without_rule"] or 10 ** 6, m["pid"]))

        total_w = sum(abs(m["weight_change"]) for m in moves)
        known = [m for m in moves if m["rpv"] is not None]
        missing_rpv = sorted(m["pid"] for m in moves if m["rpv"] is None)
        known_w = sum(abs(m["weight_change"]) for m in known)
        estimate = None
        if visits is not None and known and not mixed_currency:
            estimate = sum(m["weight_change"] * m["rpv"] * visits for m in known)
        coverage = (known_w / total_w) if total_w else None
        if coverage is not None and coverage < Decimal(str(RULES["min_rpv_coverage"])):
            r_warn.append("Partial estimate: products with a known RPV carry less than min_rpv_coverage of the movement; "
                          "products with no RPV are left out, not counted as 0.")
        share = (estimate / q_revenue) if estimate is not None and q_revenue else None

        flags, sellers = [], []
        if median_rpv is not None:
            low_pins = [x["pid"] for x in applied if set(x["kinds"]) & {"pin", "boost"}
                        and rpv.get(x["pid"]) is not None and rpv[x["pid"]] < median_rpv]
            if low_pins:
                flags.append({"flag": "pins_below_median_rpv", "pids": low_pins,
                              "detail": "Products this rule pins or boosts earn less per visit than the page's median product."})
            sellers = [h for h in hidden if rpv.get(h["pid"]) is not None and rpv[h["pid"]] > median_rpv]
            if sellers:
                flags.append({"flag": "hides_above_median_rpv", "pids": [h["pid"] for h in sellers],
                              "confirmed": all(h["status"] == "confirmed" for h in sellers),
                              "detail": "This rule hides products that earn more per visit than the page's median product."})
        hides_confirmed_seller = any(h["status"] == "confirmed" for h in sellers)
        if sellers and not hides_confirmed_seller:
            r_warn.append("It may hide an above-median seller: confirm with a --presence-check grid before acting.")

        band = Decimal(str(RULES["neutral_band_share"]))
        if not moves and not hidden and not hidden_count and not applied:
            verdict = "no visible effect"
        elif hides_confirmed_seller:
            verdict = "hides sellers"
        elif share is None:
            verdict = "unknown"
        elif abs(share) < band:
            verdict = "neutral"
        else:
            verdict = "helps" if share > 0 else "hurts"
        big = share is not None and -share >= Decimal(str(RULES["high_priority_share"]))
        if verdict == "hides sellers" or (verdict == "hurts" and big):
            priority = "high"
        elif verdict == "hurts" or flags:
            priority = "medium"
        else:
            priority = "low"

        results.append({
            "name": name, "label": label, "rules_disabled": sorted(expected),
            "verdict": verdict, "priority": priority,
            "estimated_effect": money(estimate), "share_of_query_revenue": None if share is None else str(share.quantize(Decimal("0.0001"))),
            "applied": applied,
            "moves": [{**{k: v for k, v in m.items() if k not in ("weight_change", "rpv")},
                       "weight_change": str(m["weight_change"].quantize(Decimal("0.000001"))), "rpv": money(m["rpv"])} for m in moves],
            "hidden_count": hidden_count, "hidden": hidden,
            "num_found": {"with_rule": base.num_found, "without_rule": off.num_found},
            "missing_rpv": missing_rpv, "rpv_coverage": None if coverage is None else str(coverage.quantize(Decimal("0.01"))),
            "rules_listed_only_when_off": extra_rules,
            "flags": flags, "warnings": r_warn,
        })

    order = {"high": 0, "medium": 1, "low": 2}
    results.sort(key=lambda r: (order[r["priority"]], -abs(Decimal(r["estimated_effect"] or 0)), r["name"]))

    measured = {n for n, _ in toggled}
    for rid in ranking_ids:
        if rid not in measured:
            not_checked.append(f"Ranking rule {rid} applies but no grid with it disabled was given.")
    if algo_ids and "all_algo" not in measured:
        not_checked.append("No all_algo grid was given, so the ranking algorithm rules weren't measured.")
    not_measured = sorted(({"id": i, "type": r["type"]} for i, r in base_ids.items()
                           if r["type"] not in RULES["ranking_rule_types"] + RULES["algo_rule_types"]), key=lambda r: r["id"])

    out = {
        "ok": True, "query": a.query, "page_size": a.page_size,
        "query_metrics": None if row is None else {
            "visits": None if visits is None else int(visits), "revenue": money(q_revenue), "rpv": money(q_rpv),
            "product_views_per_visit": money(views / visits) if views is not None and visits else None},
        "currency": sorted(currency)[0] if len(currency) == 1 else None,
        "mixed_currency": mixed_currency,
        "page_median_rpv": money(median_rpv),
        "rules_found": sorted(base.rules, key=lambda r: r["id"]),
        "to_toggle": {"one_at_a_time": ranking_ids, "all_algo": algo_ids, "all": sorted(base_ids)},
        "results": results,
        "not_measured": not_measured,
        "rpv_not_found": sorted(rpv_not_found),
        "not_checked": not_checked, "warnings": warnings,
        "assumptions": [
            "Product RPV is across all of the product's traffic over the period, not this query: no tool gives a product's RPV for one query.",
            "The position-weight curve (position_weights in references/rules.json) is an assumption, not measured. " + scale_note
            + " Product views from deeper pages are attributed to page one when scaling.",
            "The estimate assumes a product earns its usual RPV wherever it sits, and ignores what shoppers would have bought instead.",
            "The grid shows a default shopper: audience-targeted rules, personalisation and A/B test buckets differ for real shoppers.",
            "Only ranking and ranking algorithm rules are removed by disabled_customization_ids; synonyms, redirects and facet rules aren't measured.",
        ],
    }
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"Can't write {a.out}: {e}")
    print(text)


if __name__ == "__main__":
    main()
