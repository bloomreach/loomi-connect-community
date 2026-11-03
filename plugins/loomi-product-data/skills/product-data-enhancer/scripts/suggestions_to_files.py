#!/usr/bin/env python3
"""Turn the assistant's product-data suggestions (JSON Lines) into files a team can review and import.

Usage:
  python3 suggestions_to_files.py [FILE.jsonl ...] --out-dir OUT [--currency USD]
                                  [--current-text] [--include-ratings] [--faq-jsonld]
                                  [--banned-terms FILE]
  cat batch1.jsonl batch2.jsonl | python3 suggestions_to_files.py - --out-dir OUT

Input is JSON Lines: one product per line, in the format in references/suggestions-format.md
({"schema": "loomi-product-suggestions", "version": "1", "product_id": ..., "suggestions": [...]}).
Several files, or "-" for stdin (the default when no file is given), are read line by line, so
batches can be concatenated and a whole catalog never has to fit in memory. Malformed lines,
lines with the wrong schema or no product_id, and repeated product IDs are reported with their
file and line number and skipped; the rest of the run carries on.

Writes, one product at a time:
  OUT/suggestions.csv       one row per suggested change: product_id, field, current, suggested,
                            source, confidence, priority, evidence, status (a cell starting with
                            =, +, -, @, tab or CR gets a leading ' so spreadsheets don't run it)
  OUT/suggestions.jsonl     one line per product: its rows, JSON-LD and checks
  OUT/jsonld/<id>.json      a schema.org Product JSON-LD block per product
  OUT/review.md             a review table per product (current vs suggested)

Rules the script enforces (and reports as warnings):
  - source must be "from data", "seen in image", "from shopper searches" or "needs a human";
    "seen in image" needs a confidence.
  - suggested text with claim words (sustainable, waterproof, organic, hypoallergenic, SPF,
    clinically ...) is marked BLOCKED unless its source is "from data" with evidence.
  - terms from --banned-terms (e.g. competitor names, one per line) are marked BLOCKED.
  - length checks: title <= 150, meta description <= 160, alt text <= 125 characters.
  - JSON-LD uses only the product's "known" values (verified data) and, unless --current-text,
    a suggested title and meta description whose source is "from data" or "from shopper
    searches". Values "seen in image" never go into JSON-LD until a person confirms them and
    moves them into "known". Ratings only with --include-ratings.
  - GTINs are checked (length and check digit); an invalid GTIN is left out.
Every row is marked "suggestion - needs human review". Standard library only; no network access.
"""
import argparse
import csv
import json
import os
import re
import sys

SOURCES = {"from data", "seen in image", "from shopper searches", "needs a human"}
LEVELS = {"high", "medium", "low"}
CLAIMS = re.compile(r"\b(sustainabl\w*|eco[- ]?friendly|organic|waterproof|water[- ]?resistant|windproof|"
                    r"hypoallergenic|non[- ]?toxic|clinically|dermatologist\w*|anti[- ]?ag(e)?ing|spf|uv protection|"
                    r"cures?|heals?|treats?|prevents?|medical|therapeutic|vegan|cruelty[- ]free|recycled|"
                    r"biodegradable|carbon[- ]neutral|fair[- ]trade|certified|guaranteed|best[- ]selling|#1|"
                    r"safe for (babies|children|kids))\b", re.I)
LIMITS = {"title": 150, "meta_description": 160, "alt_text": 125}
AVAIL = {"true": "InStock", "in stock": "InStock", "instock": "InStock", "in_stock": "InStock",
         "available": "InStock", "false": "OutOfStock", "out of stock": "OutOfStock",
         "outofstock": "OutOfStock", "out_of_stock": "OutOfStock", "preorder": "PreOrder",
         "pre-order": "PreOrder", "backorder": "BackOrder", "discontinued": "Discontinued"}
STATUS = "suggestion - needs human review"
SCHEMA = "loomi-product-suggestions"
VERSION = "1"


def as_text(v):
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return " | ".join(as_text(x) for x in v)
    if isinstance(v, dict):
        if "q" in v or "question" in v:
            return f"Q: {v.get('q') or v.get('question')} A: {v.get('a') or v.get('answer')}"
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def gtin_ok(g):
    g = re.sub(r"\D", "", str(g))
    if len(g) not in (8, 12, 13, 14):
        return None
    digits = [int(c) for c in g]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits[:-1])))
    return g if (10 - total % 10) % 10 == digits[-1] else None


def number(v):
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def check_row(s, banned):
    """Return (status, warnings) for one suggestion."""
    warns = []
    field, src = s.get("field", ""), (s.get("source") or "").strip().lower()
    text = as_text(s.get("suggested"))
    status = STATUS
    if src not in SOURCES:
        warns.append(f"{field}: unknown source '{s.get('source')}'")
    if src == "seen in image" and (s.get("confidence") or "").lower() not in LEVELS:
        warns.append(f"{field}: 'seen in image' needs a confidence (high/medium/low)")
    m = CLAIMS.search(text)
    if m and not (src == "from data" and s.get("evidence")):
        status = f"BLOCKED: unverified claim '{m.group(0)}' - needs a human"
        warns.append(f"{field}: claim '{m.group(0)}' without evidence from data")
    for term in banned:
        if re.search(r"\b" + re.escape(term) + r"\b", text, re.I):
            status = f"BLOCKED: contains '{term}'"
            warns.append(f"{field}: contains banned term '{term}'")
    limit = LIMITS.get(field)
    if limit:
        for part in (s.get("suggested") if isinstance(s.get("suggested"), list) else [text]):
            if len(as_text(part)) > limit:
                warns.append(f"{field}: {len(as_text(part))} characters (limit {limit})")
    return status, warns


def jsonld(p, args, texts):
    k = p.get("known", {}) or {}
    warns = []
    doc = {"@context": "https://schema.org", "@type": "Product"}
    name = k.get("name") if args.current_text else (texts.get("title") or k.get("name"))
    desc = k.get("description") if args.current_text else (texts.get("meta_description") or k.get("description"))
    if name:
        doc["name"] = name
    if desc:
        doc["description"] = re.sub(r"<[^>]+>", " ", str(desc)).strip()
    for key in ("sku", "mpn", "color", "material", "category", "size", "pattern", "url"):
        if k.get(key) not in (None, "", []):
            doc[key] = k[key]
    if k.get("sku") is None and p.get("product_id"):
        doc["sku"] = str(p["product_id"])
    if k.get("gtin"):
        g = gtin_ok(k["gtin"])
        if g:
            doc[{8: "gtin8", 12: "gtin12", 13: "gtin13", 14: "gtin14"}[len(g)]] = g
        else:
            warns.append(f"GTIN '{k['gtin']}' failed the length or check-digit test; left out")
    if k.get("brand"):
        doc["brand"] = {"@type": "Brand", "name": str(k["brand"]).strip()}
    imgs = k.get("image") or k.get("images")
    if imgs:
        doc["image"] = imgs if isinstance(imgs, list) else [imgs]
    price, sale = number(k.get("price")), number(k.get("sale_price"))
    pay = sale if sale and price and sale < price else price
    if pay is not None:
        offer = {"@type": "Offer", "price": f"{pay:.2f}"}
        cur = k.get("currency") or args.currency
        if cur:
            offer["priceCurrency"] = cur
        else:
            warns.append("no currency: pass --currency or add known.currency")
        av = AVAIL.get(str(k.get("availability")).strip().lower()) if k.get("availability") is not None else None
        if av:
            offer["availability"] = "https://schema.org/" + av
        elif k.get("availability") is not None:
            warns.append(f"availability '{k.get('availability')}' not mapped; left out (confirm its meaning)")
        if k.get("url"):
            offer["url"] = k["url"]
        if k.get("condition"):
            offer["itemCondition"] = "https://schema.org/" + str(k["condition"])
        doc["offers"] = offer
    else:
        warns.append("no price: Offer left out")
    if args.include_ratings and k.get("rating") and k.get("review_count"):
        doc["aggregateRating"] = {"@type": "AggregateRating", "ratingValue": k["rating"], "reviewCount": k["review_count"]}
    out = [doc]
    faq = texts.get("faq_list")
    if args.faq_jsonld and faq:
        out.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": f.get("q") or f.get("question"),
             "acceptedAnswer": {"@type": "Answer", "text": f.get("a") or f.get("answer")}} for f in faq]})
    return (out[0] if len(out) == 1 else out), warns


def iter_lines(paths, problems):
    """Yield (where, product) for each valid line of each input, streaming."""
    for path in paths:
        name = "stdin" if path == "-" else path
        try:
            f = sys.stdin if path == "-" else open(path, encoding="utf-8")
        except OSError as e:
            problems.append(f"{name}: unreadable ({e.strerror})")
            continue
        try:
            for n, line in enumerate(f, 1):
                if not line.strip():
                    continue
                where = f"{name}:{n}"
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    problems.append(f"{where}: malformed JSON ({e.msg}); skipped")
                    continue
                if not isinstance(obj, dict):
                    problems.append(f"{where}: not a JSON object; skipped")
                    continue
                if obj.get("schema") != SCHEMA:
                    problems.append(f"{where}: schema is {obj.get('schema')!r}, expected {SCHEMA!r}; skipped")
                    continue
                if str(obj.get("version")) != VERSION:
                    problems.append(f"{where}: version {obj.get('version')!r} (this script reads {VERSION!r}); read anyway")
                if not obj.get("product_id"):
                    problems.append(f"{where}: no product_id; skipped")
                    continue
                yield where, obj
        finally:
            if f is not sys.stdin:
                f.close()


def csv_safe(v):
    """Stop spreadsheets running a cell as a formula: prefix =, +, -, @, tab or CR with '."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", default=["-"], help=".jsonl files, or - for stdin (default)")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--currency", help="ISO 4217 code, e.g. USD, used when a line has no currency")
    ap.add_argument("--current-text", action="store_true", help="use current title/description in JSON-LD")
    ap.add_argument("--include-ratings", action="store_true", help="add aggregateRating (only if shown on the page)")
    ap.add_argument("--faq-jsonld", action="store_true", help="also emit FAQPage markup for the shopper questions")
    ap.add_argument("--banned-terms", help="file with one term per line (e.g. competitor names)")
    args = ap.parse_args()
    banned = []
    if args.banned_terms:
        with open(args.banned_terms, encoding="utf-8") as f:
            banned = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]

    os.makedirs(os.path.join(args.out_dir, "jsonld"), exist_ok=True)
    cols = ["product_id", "field", "current", "suggested", "source", "confidence", "priority", "evidence", "status"]
    problems, seen = [], {}
    n_products = n_rows = n_blocked = n_warn = 0
    with open(os.path.join(args.out_dir, "suggestions.csv"), "w", newline="", encoding="utf-8") as csv_f, \
            open(os.path.join(args.out_dir, "suggestions.jsonl"), "w", encoding="utf-8") as jl_f, \
            open(os.path.join(args.out_dir, "review.md"), "w", encoding="utf-8") as md_f:
        writer = csv.DictWriter(csv_f, fieldnames=cols)
        writer.writeheader()
        md_f.write("All values are suggestions for human review. Nothing has been changed in any catalog.\n\n")
        for where, p in iter_lines(args.inputs, problems):
            pid = str(p["product_id"])
            if pid in seen:
                problems.append(f"{where}: product_id {pid} already read at {seen[pid]}; skipped "
                                "(remove the older line to keep a redo)")
                continue
            seen[pid] = where
            texts, prod_warns, prod_rows = {}, [], []
            if not p.get("images_viewed"):
                prod_warns.append("images not viewed: text-only suggestions")
            for s in p.get("suggestions") or []:
                if not isinstance(s, dict):
                    prod_warns.append("a suggestion is not an object; skipped")
                    continue
                status, warns = check_row(s, banned)
                prod_warns += warns
                src = (s.get("source") or "").strip().lower()
                row = {"product_id": pid, "field": s.get("field", ""), "current": as_text(s.get("current")),
                       "suggested": "" if src == "needs a human" else as_text(s.get("suggested")),
                       "source": s.get("source", ""), "confidence": s.get("confidence", ""),
                       "priority": s.get("priority", ""), "evidence": s.get("evidence", ""), "status": status}
                if src == "needs a human":
                    row["evidence"] = (row["evidence"] + " | question: " + as_text(s.get("suggested"))).strip(" |")
                prod_rows.append(row)
                if status == STATUS and s.get("field") in ("title", "meta_description"):
                    if src in ("from data", "from shopper searches"):
                        texts[s["field"]] = as_text(s.get("suggested"))
                    elif src == "seen in image":
                        prod_warns.append(f"suggested {s['field']} relies on the image; JSON-LD keeps the current "
                                          "value until a person confirms it")
                if status == STATUS and s.get("field") == "faq" and isinstance(s.get("suggested"), list):
                    texts["faq_list"] = s["suggested"]
            args_line = argparse.Namespace(**vars(args))
            args_line.currency = args.currency or p.get("currency")
            ld, ld_warns = jsonld(p, args_line, texts)
            prod_warns += ld_warns

            writer.writerows({k: csv_safe(v) for k, v in r.items()} for r in prod_rows)
            with open(os.path.join(args.out_dir, "jsonld", re.sub(r"[^A-Za-z0-9_.-]", "_", pid) + ".json"),
                      "w", encoding="utf-8") as f:
                json.dump(ld, f, indent=2, ensure_ascii=False)
            jl_f.write(json.dumps({"schema": SCHEMA + "-review", "version": VERSION, "product_id": pid,
                                   "images_viewed": bool(p.get("images_viewed")), "status": STATUS,
                                   "rows": prod_rows, "jsonld": ld, "warnings": prod_warns}, ensure_ascii=False) + "\n")
            md = [f"### {p.get('title') or (p.get('known') or {}).get('name') or pid} ({pid})\n",
                  f"Images: {'viewed' if p.get('images_viewed') else 'NOT viewed (text-only suggestions)'}\n",
                  "| Field | Current | Suggested | Source | Confidence | Priority | Status |",
                  "|---|---|---|---|---|---|---|"]
            for r in prod_rows:
                cur = r["current"].replace("|", "/")[:80]
                sug = (r["suggested"] or r["evidence"]).replace("|", "/")[:160]
                md.append(f"| {r['field']} | {cur} | {sug} | {r['source']} | {r['confidence']} | {r['priority']} | {r['status']} |")
            if prod_warns:
                md.append("\nChecks: " + "; ".join(prod_warns))
            md_f.write("\n".join(md) + "\n\n")
            for f in (csv_f, jl_f, md_f):
                f.flush()

            n_products += 1
            n_rows += len(prod_rows)
            n_blocked += sum(r["status"].startswith("BLOCKED") for r in prod_rows)
            n_warn += len(prod_warns)
            for w in prod_warns:
                print(f"WARNING {pid}: {w}", file=sys.stderr)

    for msg in problems:
        print("INPUT " + msg, file=sys.stderr)
    print(f"{n_products} products, {n_rows} suggestions ({n_blocked} blocked), {n_warn} warnings, "
          f"{len(problems)} input problems -> {args.out_dir}")


if __name__ == "__main__":
    main()
