#!/usr/bin/env python3
"""Run the redirect audit checks on saved Loomi Connect responses.

Standard library only, no network. It never fetches redirect URLs; it only
checks their shape.

Usage:
  python3 scripts/redirect_checks.py --redirects <file> [--redirects <file> ...]
      [--synonyms <file> ...] [--rules <file> ...] [--queries <file> ...]
      [--min-sessions 50]

--redirects  search_redirects responses: list pages and/or single-rule
             responses (rule_id=...). Detail responses carry the URL and match
             type; list rows don't, and are reported as "URL not fetched".
--synonyms   list_synonyms_user / list_synonyms_br_generated responses.
--rules      list_site_search_ranking_rules / list_site_search_media_rules
             responses.
--queries    get_discovery_query_performance responses.

Prints Markdown: one table of findings, then navigational redirect candidates.
"""
import argparse
import json
import math
import re
import sys
from collections import defaultdict
from urllib.parse import urlsplit

NAVIGATIONAL = [
    "return", "returns", "return policy", "refund", "exchange", "exchanges",
    "store locator", "store", "stores", "store near me", "stores near me", "find a store",
    "gift card", "gift cards", "giftcard", "gift certificate", "e gift card", "egift",
    "track order", "order status", "track my order", "tracking", "my order", "orders",
    "contact", "contact us", "customer service", "help", "faq", "faqs",
    "shipping", "delivery", "free shipping", "size guide", "size chart", "sizing",
    "login", "log in", "sign in", "account", "my account", "register",
    "careers", "jobs", "about", "about us", "app", "download app", "mobile app",
    "coupon", "coupons", "promo code", "discount code", "voucher", "student discount",
    "warranty", "klarna", "afterpay", "paypal", "financing", "credit card",
    "newsletter", "catalog", "catalogue", "rewards", "loyalty", "wishlist",
    "unsubscribe", "privacy", "terms", "sitemap", "blog",
]
# Words that mark a short query as navigational wherever they appear ("klarna payment", "paypal
# refund"). Words that also describe products ("size", "track", "mobile", "free", "contact", "order")
# only count as part of a phrase above ("size guide", "track order") or as the whole query.
NAV_WORDS = {"refund", "refunds", "klarna", "afterpay", "paypal", "giftcard", "egift", "voucher", "vouchers",
             "coupon", "coupons", "login", "unsubscribe", "newsletter", "sitemap", "careers", "faq", "faqs",
             "warranty", "wishlist"}
NAV_STEMS = {" ".join(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in p.split()) for p in NAVIGATIONAL}

SUSPECT_HOST = re.compile(r"(^|[.-])(localhost|staging|stage|stg|dev|qa|uat|test|preview|sandbox)([.-]|$)|example\.(com|org)", re.I)
SEASONAL = re.compile(r"(black[-_ ]?friday|cyber[-_ ]?monday|christmas|xmas|holiday|halloween|easter|valentine|"
                      r"summer[-_ ]?sale|winter[-_ ]?sale|clearance|20[12]\d)", re.I)


def load(path):
    with open(path, encoding="utf-8") as f:
        doc = check(json.load(f), path)
    while isinstance(doc, dict) and "result" in doc and isinstance(doc["result"], dict):
        doc = doc["result"]
    return doc


def check(doc, path):
    """Stop when Loomi Connect returned an error as data (success: false) instead of results."""
    for d in (doc, doc.get("result") if isinstance(doc, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            sys.exit(f"{path}: Loomi Connect returned an error: {d.get('error') or 'no error text'}. "
                     "This check couldn't run; don't treat it as 'nothing found'.")
    return doc


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


def is_navigational(q):
    """True for a query that asks for a site page rather than products."""
    nq = norm_q(q)
    words = nq.split()
    if not words:
        return False
    sq = stem(nq)
    if sq in NAV_STEMS:
        return True  # the whole query is a navigational term ("returns", "store", "size chart")
    if len(words) > 4:
        return False
    if any(" " in p and re.search(rf"\b{re.escape(p)}\b", sq) for p in NAV_STEMS):
        return True  # contains a navigational phrase ("track my order uk", "size guide women")
    return len(words) <= 3 and bool(set(words) & NAV_WORDS)


def rows_of(doc):
    data = doc.get("data", doc) if isinstance(doc, dict) else doc
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    if isinstance(data, dict) and "rows" in data:
        data = data["rows"]
    if isinstance(data, dict):
        return [data]
    return data or []


def norm_q(q):
    q = re.sub(r"[^\w\s]", " ", (q or "").lower())
    return re.sub(r"\s+", " ", q).strip()


def stem(q):
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in norm_q(q).split())


def url_issues(url):
    issues = []
    if not url:
        return ["empty URL"]
    u = url.strip()
    if u != url:
        issues.append("leading or trailing whitespace")
    if " " in u:
        issues.append("space inside URL")
    if u.lower().startswith(("javascript:", "data:", "mailto:")):
        issues.append("non-web scheme")
        return issues
    if not re.match(r"^https?://", u, re.I):
        issues.append("no scheme (http/https); relies on the front end to add one" if not u.startswith("/")
                      else "relative path; fine only if the front end resolves it")
        u = "https://" + u.lstrip("/") if not u.startswith("/") else "https://site.invalid" + u
    elif u.lower().startswith("http://"):
        issues.append("http, not https")
    parts = urlsplit(u)
    host = parts.hostname or ""
    if not host or "." not in host:
        issues.append("no valid host")
    if SUSPECT_HOST.search(host):
        issues.append(f"non-production-looking host ({host})")
    if "//" in parts.path:
        issues.append("double slash in path")
    if re.search(r"\.(html?|php)\.\1$", parts.path, re.I) or re.search(r"[.,;)]$", u):
        issues.append("odd ending")
    if re.search(r"\{|\}|%7B|TODO|TBD|xxx|placeholder|undefined|null$", u, re.I):
        issues.append("placeholder text")
    if re.search(r"utm_|gclid=", u, re.I):
        issues.append("tracking parameters in destination")
    if SEASONAL.search(parts.path + "?" + parts.query):
        issues.append("seasonal or dated destination; check it still exists")
    return issues


def norm_url(url):
    u = (url or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.split("#")[0].rstrip("/")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser()
    ap.add_argument("--redirects", action="append", default=[])
    ap.add_argument("--synonyms", action="append", default=[])
    ap.add_argument("--rules", action="append", default=[])
    ap.add_argument("--queries", action="append", default=[])
    ap.add_argument("--min-sessions", type=int, default=50)
    a = ap.parse_args()
    if not a.redirects:
        sys.exit("Pass at least one --redirects file.")

    # Merge redirects: detail rows win over list rows.
    red = {}
    for p in a.redirects:
        for r in rows_of(load(p)):
            rid = r.get("id")
            item = (r.get("customizationItems") or {}).get("redirect") or {}
            entry = red.setdefault(rid, {"id": rid, "url": None, "detail": False})
            fields = {
                "name": r.get("name") or item.get("ruleName") or entry.get("name") or "(unnamed)",
                "enabled": r.get("enabled", item.get("isEnabled")),
                "duration": r.get("durationTag"),
                "abtest": r.get("isAbTestLive"),
                "audiences": r.get("audiences"),
                "queries": [(q.get("query"), q.get("matchType") or entry.get("mt", {}).get(q.get("query")))
                            for q in r.get("queries") or []],
            }
            entry.update({k: v for k, v in fields.items() if v is not None})
            if "customizationItems" in r:
                entry["detail"] = True
                entry["url"] = item.get("url")
                entry["mt"] = {q: m for q, m in entry["queries"]}

    findings = []

    def add(prio, rid, issue, evidence, action):
        r = red.get(rid, {})
        findings.append((prio, rid, r.get("name", ""), ", ".join(q for q, _ in r.get("queries", [])), issue, evidence, action))

    live = {k: v for k, v in red.items() if v.get("enabled") and v.get("duration") != "expired"}

    for rid, r in red.items():
        if r.get("enabled") and r.get("duration") == "expired":
            add("Clean up", rid, "Expired but still enabled", "durationTag expired", "Disable or delete")
        elif r.get("enabled") is False:
            add("Clean up", rid, "Disabled", "enabled false", "Delete if nobody needs it")

    # URL shape and duplicate URLs.
    by_url = defaultdict(list)
    hosts = defaultdict(int)
    for rid, r in red.items():
        if not r["detail"]:
            add("Review", rid, "URL not fetched", "only the list row was saved", "Fetch with search_redirects rule_id")
            continue
        iss = url_issues(r["url"])
        if iss:
            hard = any(x.startswith(("empty", "space", "non-web", "no valid", "non-production", "placeholder")) for x in iss)
            add("Fix now" if hard and r.get("enabled") else "Review", rid, "URL shape", "; ".join(iss),
                "Correct the URL, then check it loads")
        by_url[norm_url(r["url"])].append(rid)
        h = urlsplit("https://" + norm_url(r["url"])).hostname
        if h:
            hosts[h] += 1
    if hosts:
        main_host = max(hosts, key=hosts.get)
        for rid, r in red.items():
            h = urlsplit("https://" + norm_url(r.get("url") or "")).hostname if r.get("url") else None
            if h and h != main_host and hosts[main_host] > 1:
                add("Review", rid, "Different host from other redirects", f"{h} vs {main_host}", "Confirm it is intended")
    for u, ids in by_url.items():
        if u and len(ids) > 1:
            for rid in ids:
                add("Clean up", rid, "Same destination as another redirect",
                    "shared with " + ", ".join(str(i) for i in ids if i != rid), "Merge the queries into one rule")

    # Same or overlapping queries.
    qmap = defaultdict(list)
    for rid, r in live.items():
        for q, mt in r["queries"]:
            qmap[stem(q)].append((rid, q, mt))
    for key, hits in qmap.items():
        ids = {h[0] for h in hits}
        if len(ids) > 1:
            urls = {norm_url(red[i].get("url") or "?") for i in ids}
            for rid, q, _ in hits:
                add("Fix now" if len(urls) > 1 else "Clean up", rid, "Same query on several redirects",
                    f"'{key}' on rules {sorted(ids)}; {len(urls)} destination(s)",
                    "Keep one; check audiences first" if len(urls) > 1 else "Merge")
    phrase = [(rid, norm_q(q)) for rid, r in live.items() for q, mt in r["queries"] if mt == "PHRASE_MATCH"]
    allq = [(rid, norm_q(q)) for rid, r in live.items() for q, _ in r["queries"]]
    for prid, pq in phrase:
        for rid, q in allq:
            if rid != prid and q != pq and re.search(rf"\b{re.escape(pq)}\b", q):
                add("Review", rid, "Overlaps a phrase-match redirect",
                    f"'{q}' also contains '{pq}' (rule {prid})", "Check which fires with the product grid")

    # Broad queries.
    qperf = []
    for p in a.queries:
        for row in rows_of(load(p)):
            if isinstance(row, dict) and row.get("query"):
                qperf.append(row)
    for rid, r in live.items():
        for q, mt in r["queries"]:
            nq = norm_q(q)
            reasons = []
            if len(nq) <= 3:
                reasons.append("very short query")
            if mt == "PHRASE_MATCH" and len(nq.split()) == 1:
                reasons.append("one-word phrase match")
            if mt == "PHRASE_MATCH" and qperf:
                n = sum(1 for row in qperf if re.search(rf"\b{re.escape(nq)}\b", norm_q(row["query"])) and norm_q(row["query"]) != nq)
                if n:
                    reasons.append(f"{n} other tracked queries contain it")
            if reasons:
                add("Fix now" if mt == "PHRASE_MATCH" else "Review", rid, "May hijack broad searches",
                    "; ".join(reasons), "Use exact match, or a more specific query")

    # Redirect queries that still show up in search traffic.
    sess = {}
    for row in qperf:
        sess[norm_q(row["query"])] = row
    for rid, r in live.items():
        for q, _ in r["queries"]:
            row = sess.get(norm_q(q))
            if row and (num(row.get("browse_sessions")) or 0) > 0:
                add("Review", rid, "Redirect query has search-results traffic",
                    f"{row.get('browse_sessions')} sessions, bounce {row.get('bounce_rate')}",
                    "Check it fires (grid keywordRedirect); the rule may be new, scheduled or not matching")

    # Synonyms.
    for p in a.synonyms:
        for s in rows_of(load(p)):
            if not isinstance(s, dict) or not s.get("enabled", True):
                continue
            src = norm_q(s.get("sourceSynonym"))
            tgts = [norm_q(t) for t in (s.get("targetSynonym") or "").split(",") if t.strip()]
            for rid, r in live.items():
                for q, _ in r["queries"]:
                    nq = norm_q(q)
                    if nq == src and any(t != nq for t in tgts):
                        add("Review", rid, "Redirect query is a synonym source",
                            f"synonym {s.get('id')} ({s.get('synonymType')}) never applies while the redirect fires",
                            "Remove one, or hand off to discovery-synonym-review")
                    elif nq in tgts and src != nq:
                        add("Review", rid, "Synonym points at a redirect query",
                            f"'{src}' expands to '{nq}' but does not redirect",
                            "Add '" + src + "' to the redirect if it means the same thing")

    # Ranking or media rules on redirected queries.
    for p in a.rules:
        for rule in rows_of(load(p)):
            if not isinstance(rule, dict) or not rule.get("enabled"):
                continue
            for qq in rule.get("queries") or []:
                nq = norm_q(qq.get("query"))
                for rid, r in live.items():
                    if any(norm_q(q) == nq for q, _ in r["queries"]):
                        add("Clean up", rid, f"Enabled {rule.get('ruleType')} rule on a redirected query",
                            f"rule {rule.get('id')} never shows while the redirect fires",
                            "Disable the rule, or remove the query from the redirect")

    order = {"Fix now": 0, "Clean up": 1, "Review": 2}
    findings.sort(key=lambda f: (order[f[0]], str(f[1])))
    print(f"## Redirect checks\n\n{len(red)} redirects ({len(live)} enabled and not expired); "
          f"{sum(1 for r in red.values() if r['detail'])} with details.\n")
    print("| Priority | Rule | Name | Queries | Issue | Evidence | Action |\n|---|---|---|---|---|---|---|")
    for f in findings:
        print("| " + " | ".join(str(x).replace("|", "/") for x in f) + " |")

    # Navigational candidates.
    redirected = {stem(q) for r in live.values() for q, _ in r["queries"]}
    cands = []
    for row in qperf:
        nq = norm_q(row["query"])
        s = num(row.get("browse_sessions"))
        s = s if s is not None else (num(row.get("visits")) or 0)
        if s < a.min_sessions or stem(nq) in redirected:
            continue
        if is_navigational(nq):
            cands.append((s, row))
    print("\n## Navigational queries without a redirect\n")
    if not cands:
        print("None found in the saved query tables (check the threshold and the table size).")
    else:
        print("| Query | Sessions | Bounce | Product views | Revenue |\n|---|---|---|---|---|")
        for s, row in sorted(cands, key=lambda c: -c[0]):
            cells = [row.get(k) for k in ("bounce_rate", "product_page_views", "revenue")]
            print(f"| {row['query']} | {s:g} | " + " | ".join("-" if c is None else str(c) for c in cells) + " |")


if __name__ == "__main__":
    main()
