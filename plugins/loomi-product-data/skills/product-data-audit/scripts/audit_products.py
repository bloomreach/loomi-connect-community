#!/usr/bin/env python3
"""Score product data for search engines and AI answers (SEO, AEO, GEO) and rank what to fix first.

Usage:
  python3 audit_products.py [LABEL=]FILE [...] [--performance FILE ...] [--queries FILE ...]
                            [--synonyms FILE] [--jsonl OUT.jsonl] [--top N] [--markdown]

FILE is product data the assistant already fetched, either
  - a .jsonl file (or "-" for stdin) with one product record per line: read line by line, and
    malformed lines are reported with their line numbers and skipped; or
  - one saved tool response per file: a Discovery product grid page
    (search_discovery_product_grid_insights, data.response.docs), a Discovery catalog record
    (search_discovery_catalog_products), or an Engagement item list (search_catalog_items).
Prefix a file with a category label, e.g. "men/pants=grid_pants_p1.json", to tell the script
which category its products belong to (the grid's fl can't return category_paths).
Inputs are read twice (catalog-wide facts, then scoring), one record at a time, so a whole
catalog never has to fit in memory; stdin is spooled to a temporary file for the second pass.

Options:
  --performance FILE ...  get_discovery_product_performance_table pages: weights products by
                          revenue and visits. Products missing from it had no views.
  --queries FILE ...      get_discovery_query_performance pages: the words shoppers use, for the
                          vocabulary check (V1).
  --synonyms FILE         extra term groups for V1: a JSON list of lists, e.g. [["sofa","couch"]].
  --jsonl OUT             write one result line per product as it is scored ("-" for stdout):
                          {"schema": "loomi-product-audit", "version": "1", "pid": ..., "score": ...,
                          "priority": ..., "gaps": [...]}. See references/audit-rubric.md.
  --top N                 products to list (default 50)
  --min-desc N            description shorter than this (characters of text) is thin (default 150)
  --markdown              print Markdown instead of JSON

Scoring follows references/audit-rubric.md: every product starts at 100 and loses points per
gap (codes T1-T5, D1-D6, A1-A3, S1-S3, I1-I3, V1). Priority = (100 - score) x (0.2 + importance),
where importance = 0.6 x revenue percentile + 0.4 x visits percentile (0 with no performance data).
Text only: it never looks at images. Standard library only; no network access.
"""
import argparse
import collections
import heapq
import html
import json
import math
import os
import re
import shutil
import sys
import tempfile

SCHEMA = "loomi-product-audit"
VERSION = "1"

ALIASES = {
    "id": ["pid", "product_id", "item_id", "id", "prod_id"],
    "title": ["title", "name", "product_title", "product_name"],
    "description": ["description", "long_description", "desc", "product_description"],
    "brand": ["brand", "product_brand", "manufacturer"],
    "colour": ["colors", "color", "colour", "shade"],
    "material": ["material", "fabric", "metal", "materials"],
    "size": ["product_size", "size", "sizes", "volume"],
    "gender": ["gender", "department"],
    "fit": ["fit"],
    "pattern": ["pattern"],
    "care": ["care", "care_instructions"],
    "dimensions": ["dimensions", "length", "product_length", "width", "height", "depth", "weight"],
    "price": ["price"],
    "sale_price": ["sale_price"],
    "availability": ["availability", "stock_level", "in_stock", "availability_status", "stock"],
    "gtin": ["gtin", "gtin13", "gtin12", "gtin14", "ean", "upc", "barcode"],
    "mpn": ["mpn", "model", "model_number"],
    "images": ["large_image", "thumb_image", "image", "image_url", "images", "additional_images", "swatch_image"],
    "alt": ["alt_text", "image_alt", "alt"],
    "url": ["url", "product_url", "link"],
}

VERTICALS = {
    "footwear": "shoe shoes sneaker sneakers trainer trainers boot boots sandal sandals heel heels loafer loafers slipper slippers flats",
    "jewellery": "ring rings necklace necklaces bracelet bracelets earring earrings pendant pendants bangle bangles anklet jewellery jewelry",
    "beauty": "lipstick mascara foundation bronzer blush eyeliner serum moisturizer moisturiser cleanser primer concealer highlighter gloss palette contour exfoliator shampoo conditioner lotion makeup skincare liner",
    "bags": "bag bags handbag handbags backpack backpacks tote totes purse purses wallet wallets clutch",
    "home": "sofa couch chair table lamp rug bed mattress cushion curtain desk shelf bookcase",
    "electronics": "phone laptop headphones earbuds speaker tv television camera charger cable monitor",
    "apparel": "shirt shirts t-shirt tee top tops blouse dress dresses skirt skirts jeans trousers pants joggers shorts suit suits blazer jacket coat sweater jumper hoodie sweatshirt cardigan leggings chinos kurta jumpsuit activewear tracksuit",
}
TYPE_WORDS = {w: v for v, words in VERTICALS.items() for w in words.split()}

# required, recommended attributes per vertical (see references/audit-rubric.md)
EXPECTED = {
    "apparel": (["colour", "material", "size", "gender"], ["fit", "pattern", "care"]),
    "footwear": (["colour", "material", "size", "gender"], []),
    "jewellery": (["material", "colour"], ["dimensions"]),
    "beauty": ([], ["colour", "size"]),
    "bags": (["colour", "material"], ["dimensions"]),
    "home": (["colour", "material", "dimensions"], []),
    "electronics": (["mpn"], ["dimensions"]),
    "general": ([], ["colour", "material"]),
}

COLOURS = ("black white grey gray blue navy red green yellow pink purple brown beige khaki olive orange "
           "maroon burgundy teal cream ivory gold silver tan mustard lavender peach coral charcoal").split()
VAGUE = {"", "na", "n/a", "none", "other", "multi", "misc", "light", "medium", "dark", "various", "assorted", "-", "null"}
MATERIALS = ("cotton polyester viscose rayon linen wool leather silk denim nylon elastane spandex lycra "
             "cashmere suede canvas acrylic modal").split()
PROMO = re.compile(r"\b(sale|free shipping|best price|cheap|buy now|discount|offer|limited time|hot deal|#1|best seller)\b", re.I)
STUFFING = re.compile(r"\bbuy\b.{0,80}\bonline\b|\bat best price\b|\bbuy .{0,40} at\b", re.I)
CLAIMS = re.compile(r"\b(sustainable|eco[- ]?friendly|organic|waterproof|water[- ]?resistant|hypoallergenic|"
                    r"non[- ]?toxic|clinically|dermatologist|anti[- ]?ageing|anti[- ]?aging|uv|spf|cure|heals?|"
                    r"vegan|cruelty[- ]free|recycled|biodegradable|rated \d(\.\d)? stars?|best[- ]selling)\b", re.I)
DEFAULT_GROUPS = [
    ["trousers", "pants"], ["joggers", "track pants", "sweatpants"], ["sneakers", "trainers"],
    ["t-shirt", "tee", "tshirt"], ["hoodie", "sweatshirt"], ["jumper", "sweater", "pullover"],
    ["necklace", "pendant", "chain"], ["earrings", "studs"], ["sofa", "couch"], ["handbag", "purse"],
    ["moisturizer", "moisturiser", "face cream"], ["blazer", "sport coat"], ["vest", "waistcoat", "tank top"],
]
STOP = set("a an and the for with of in on to by men women mens womens men's women's kids girls boys".split())

POINTS = {"T1": 8, "T2": 6, "T3": 3, "T4": 3, "T5": 5, "D1": 15, "D1s": 10, "D2": 8, "D3": 6, "D4": 8,
          "D5": 2, "D6": 3, "A1": 5, "A1r": 2, "A2": 4, "A3": 6, "A3x": 3, "S1": 4, "S2": 6, "S3": 3,
          "I1": 15, "I2": 2, "I3": 2, "V1": 5}
GAP_TEXT = {
    "T1": "title too short or too long", "T2": "title has no product type", "T3": "brand not in title",
    "T4": "colour not in title", "T5": "promo words, shouting or repetition in title",
    "D1": "no description", "D1s": "thin description", "D2": "boilerplate description shared with other products",
    "D3": "description only repeats the title", "D4": "keyword-stuffed description", "D5": "raw HTML or entities in description",
    "D6": "claims to verify", "A1": "missing key attribute", "A1r": "missing recommended attribute",
    "A2": "vague attribute value", "A3": "data conflict", "A3x": "attribute only in the description",
    "S1": "no GTIN or MPN", "S2": "price problem", "S3": "no availability", "I1": "no image",
    "I2": "only one image", "I3": "no image alt text", "V1": "not using the words shoppers search for",
}


def load(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # some clients save a wrapper line before the JSON
        start = text.find("{")
        data = json.loads(text[start:])
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            raise ToolError(f"{path}: Loomi Connect returned an error: {d.get('error') or d.get('message') or 'no error text'}. "
                            "This check couldn't run; don't treat it as 'nothing found'.")
    return data


class ToolError(Exception):
    """A saved response that says success: false."""


def find_records(obj):
    """Return a list of flat product dicts from any of the supported shapes."""
    if isinstance(obj, dict):
        resp = obj.get("data", {}).get("response") if isinstance(obj.get("data"), dict) else None
        if isinstance(resp, dict) and isinstance(resp.get("docs"), list):
            return resp["docs"]
        for key in ("result", "data", "items", "products", "docs", "rows"):
            if key in obj:
                found = find_records(obj[key])
                if found:
                    return found
        if "attributes" in obj and isinstance(obj["attributes"], dict):
            rec = dict(obj["attributes"])
            rec.setdefault("pid", obj.get("id"))
            return [rec]
        return []
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        out = []
        for x in obj:
            if "attributes" in x and isinstance(x["attributes"], dict):
                rec = dict(x["attributes"])
                rec.setdefault("pid", x.get("id"))
                out.append(rec)
            else:
                out.append(x)
        if any(any(k in r for k in ALIASES["id"] + ["query"]) for r in out):
            return out
    return []


def get(rec, field):
    for key in ALIASES[field]:
        if key in rec and rec[key] not in (None, "", []):
            return rec[key]
    return None


def has_key(rec, field):
    return any(k in rec for k in ALIASES[field])


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def strip_html(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def words(s):
    return re.findall(r"[a-z0-9][a-z0-9'&-]*", (s or "").lower())


def money(v):
    """A number from a value ("$1,299.00", "12%"), or None when missing or not a number."""
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


def vertical_of(label, title):
    for w in words(title)[::-1] + words(label):
        if w in TYPE_WORDS:
            return TYPE_WORDS[w]
    return "general"


def skeleton(desc, title, brand):
    """Description with the product's own words removed, to spot templates shared across products."""
    text = strip_html(desc).lower()
    for s in [title or "", brand or ""] + (title or "").split():
        if len(s) > 2:
            text = text.replace(s.lower(), " ")
    text = re.sub(r"[0-9]+", "#", text)
    return re.sub(r"\s+", " ", text).strip()[:160]


def percentiles(values):
    ranked = sorted(set(values))
    n = len(ranked)
    pos = {v: (i / (n - 1) if n > 1 else 1.0) for i, v in enumerate(ranked)}
    return pos


def iter_lines(path):
    """Yield (line_number, text) from a JSONL file, or from stdin for '-'."""
    f = sys.stdin if path == "-" else open(path, encoding="utf-8")
    try:
        for n, line in enumerate(f, 1):
            if line.strip():
                yield n, line
    finally:
        if f is not sys.stdin:
            f.close()


def iter_records(specs, errors):
    """Yield (label, record) from every input, one product at a time.

    .jsonl files and stdin are read line by line (one product per line; malformed lines are
    reported in `errors` and skipped). Other files are one saved tool response each (a grid page,
    a catalog record or an Engagement item list) and are read whole: a page is bounded by rows.
    """
    for label, path, name in specs:
        if path.endswith(".jsonl"):
            for n, line in iter_lines(path):
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    errors.append(f"{name}:{n}: malformed JSON ({e.msg})")
                    continue
                recs = [obj] if isinstance(obj, dict) and any(k in obj for k in ALIASES["id"]) else find_records(obj)
                if not recs:
                    errors.append(f"{name}:{n}: no product ID")
                for rec in recs:
                    yield label or rec.get("_label", ""), rec
        else:
            try:
                recs = find_records(load(path))
            except (OSError, json.JSONDecodeError) as e:
                errors.append(f"{name}: unreadable ({e})")
                continue
            for rec in recs:
                yield label, rec


class Catalog:
    """Catalog-wide facts gathered in the first pass."""

    def __init__(self):
        self.pids = set()
        self.brands = set()
        self.has_ident = self.has_alt = self.has_avail = self.multi_image = False
        self.skel = collections.Counter()
        self.vocab = collections.defaultdict(collections.Counter)

    def add(self, r):
        self.pids.add(str(get(r, "id")))
        if get(r, "brand"):
            self.brands.add(str(get(r, "brand")).strip().lower())
        self.has_ident |= has_key(r, "gtin") or has_key(r, "mpn")
        self.has_alt |= has_key(r, "alt")
        self.has_avail |= has_key(r, "availability")
        self.multi_image |= len(as_list(r.get("large_image") or r.get("images"))) > 1
        d = get(r, "description")
        if d and len(strip_html(str(d))) > 40:
            self.skel[skeleton(str(d), get(r, "title"), get(r, "brand"))] += 1
        for field in ("colour", "material", "brand"):
            for v in as_list(get(r, field)):
                self.vocab[field][str(v)] += 1

    @property
    def boiler_min(self):
        return max(5, int(0.01 * len(self.pids)))


def score_product(r, label, cat, perf, pct, queries, groups, min_desc):
    gaps = []
    pid = str(get(r, "id"))
    title = str(get(r, "title") or "")
    desc_raw = str(get(r, "description") or "")
    desc = strip_html(desc_raw)
    brand = str(get(r, "brand") or "").strip()
    vert = vertical_of(label, title)
    tl = title.lower()
    colours = [str(c).lower() for c in as_list(get(r, "colour"))]

    def add(code, detail=""):
        gaps.append((code, detail))

    if len(title) < 25 or len(title) > 150:
        add("T1", f"{len(title)} characters")
    if not any(w in TYPE_WORDS for w in words(title)) and not any(w in tl for w in words(label) if len(w) > 3):
        add("T2")
    if brand and brand.lower() not in tl and vert != "general":
        add("T3", brand)
    real_colours = [c for c in colours if c not in VAGUE]
    title_colours = [c for c in COLOURS if re.search(r"\b" + c + r"\b", tl)]
    if vert in ("apparel", "footwear", "bags") and real_colours and not title_colours:
        add("T4", real_colours[0])
    tw = [w for w in words(title) if w not in STOP and len(w) > 2]
    if PROMO.search(title) or (title.isupper() and len(title) > 10) or any(n >= 3 for n in collections.Counter(tw).values()):
        add("T5")

    if not desc:
        add("D1")
    else:
        if len(desc) < min_desc:
            add("D1s", f"{len(desc)} characters")
        sk = skeleton(desc_raw, title, brand)
        if len(desc) > 40 and cat.skel[sk] >= cat.boiler_min:
            add("D2", f"template shared by {cat.skel[sk]} products")
        rest = set(words(desc)) - set(words(title)) - set(words(brand)) - STOP
        if len(rest) < 8:
            add("D3")
        if STUFFING.search(desc) or desc.count(",") > max(8, len(desc) / 25):
            add("D4")
        if re.search(r"<[a-z]+|&[a-z]+;", desc_raw, re.I):
            add("D5")
        m = CLAIMS.search(desc + " " + title)
        if m:
            add("D6", m.group(0))

    req, rec_ = EXPECTED.get(vert, EXPECTED["general"])
    missing_req = [f for f in req if get(r, f) is None
                   and not (f == "gender" and re.search(r"\b(men|women|mens|womens|men's|women's|unisex|boys|girls|kids)\b", tl))]
    for f in missing_req[:3]:
        add("A1", f)
    for f in [f for f in rec_ if get(r, f) is None][:3]:
        add("A1r", f)
    vague = [c for c in colours if c in VAGUE]
    if vague and len(colours) == len(vague):
        add("A2", f"colour '{vague[0]}'")
    if title_colours and real_colours and not any(tc in " ".join(real_colours) for tc in title_colours):
        add("A3", f"title says {title_colours[0]}, colour field says {', '.join(sorted(set(real_colours))[:3])}")
    own = brand.lower()
    other = [b for b in cat.brands if len(b) > 3 and b != own and own not in b and b not in own
             and re.search(r"\b" + re.escape(b) + r"\b", desc.lower())]
    if brand and other and own not in desc.lower():
        add("A3", f"brand is {brand}, description names {other[0]}")
    mat = str(get(r, "material") or "").lower()
    desc_mats = [m for m in MATERIALS if re.search(r"\b" + m + r"\b", desc.lower())]
    if not mat and desc_mats and vert in ("apparel", "footwear", "bags", "home"):
        add("A3x", f"material '{desc_mats[0]}' is in the description only")

    if not (get(r, "gtin") or get(r, "mpn")):
        add("S1")
    price, sale = money(get(r, "price")), money(get(r, "sale_price"))
    if price is None:
        add("S2", "no price" if get(r, "price") is None else f"price is not a number ({get(r, 'price')!r})")
    elif price <= 0:
        add("S2", "price is 0" if price == 0 else "price below 0")
    elif sale is not None and sale > price:
        add("S2", "sale price above price")
    if cat.has_avail and get(r, "availability") is None:
        add("S3")

    imgs = [i for i in as_list(get(r, "images")) if i]
    if not imgs:
        add("I1")
    elif cat.multi_image and len(set(as_list(r.get("large_image") or r.get("images") or imgs))) < 2:
        add("I2")
    if cat.has_alt and not get(r, "alt"):
        add("I3")

    if queries:
        text = tl + " " + desc.lower()
        for g in groups:
            used = [t for t in g if re.search(r"\b" + re.escape(t) + r"s?\b", tl)]
            if not used:
                continue
            demand = {t: sum(s for q, s in queries.items() if re.search(r"\b" + re.escape(t) + r"s?\b", q)) for t in g}
            best = max(demand, key=demand.get)
            if demand[best] > 0 and demand[best] > 2 * demand.get(used[0], 0) \
                    and not re.search(r"\b" + re.escape(best) + r"s?\b", text):
                add("V1", f"uses '{used[0]}', shoppers search '{best}'")
                break

    score, caps = 100, collections.Counter()
    for code, _ in gaps:
        pts = POINTS[code]
        if code in ("A1", "A1r"):
            pts = min(pts, (15 if code == "A1" else 6) - caps[code])
            caps[code] += pts
        score -= pts
    score = max(0, score)
    rev, vis = perf.get(pid, (0.0, 0.0))
    importance = (0.6 * pct[0].get(rev, 0) + 0.4 * pct[1].get(vis, 0)) if pid in perf else 0.0
    return {
        "schema": SCHEMA, "version": VERSION,
        "pid": pid, "title": title, "category": label or vert, "vertical": vert, "score": score,
        "importance": round(importance, 3), "priority": round((100 - score) * (0.2 + importance), 1),
        "revenue": rev, "visits": vis, "in_performance_report": pid in perf,
        "gaps": [{"code": c, "gap": GAP_TEXT[c], "detail": d} for c, d in gaps],
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--performance", nargs="*", default=[])
    ap.add_argument("--queries", nargs="*", default=[])
    ap.add_argument("--synonyms")
    ap.add_argument("--jsonl", help="write one result line per product to this file ('-' for stdout)")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--min-desc", type=int, default=150)
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--out", help="write the output to this file instead of printing it (for clients that refuse shell redirects)")
    a = ap.parse_args()
    if a.out:
        sys.stdout = open(a.out, "w", encoding="utf-8")

    specs, spooled = [], []
    for spec in a.files:
        label, path = "", spec
        if "=" in spec and not os.path.exists(spec):
            label, path = spec.split("=", 1)
        name = "stdin" if path == "-" else path
        if path == "-":  # stdin can only be read once: spool it for the two passes
            tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
            shutil.copyfileobj(sys.stdin, tmp)
            tmp.close()
            path = tmp.name
            spooled.append(path)
        specs.append((label, path, name))

    perf, perf_missing = {}, 0
    for path in a.performance:
        for row in find_records(load(path)):
            pid = str(row.get("prod_id") or row.get("pid") or "")
            if pid:
                rev, vis = money(row.get("revenue")), money(row.get("visits"))
                if rev is None or vis is None:
                    perf_missing += 1
                perf[pid] = (rev or 0.0, vis or 0.0)
    queries = collections.Counter()
    for path in a.queries:
        for row in find_records(load(path)):
            q = (row.get("query") or "").lower().strip()
            if q:
                queries[q] += money(row.get("browse_sessions") or row.get("visits")) or 0.0
    groups = DEFAULT_GROUPS
    if a.synonyms:
        with open(a.synonyms, encoding="utf-8") as f:
            groups = DEFAULT_GROUPS + json.load(f)
    pct = (percentiles([v[0] for v in perf.values()]), percentiles([v[1] for v in perf.values()])) if perf else ({}, {})

    # pass 1: catalog-wide facts (templates, brands, which fields exist)
    errors, cat = [], Catalog()
    for _, r in iter_records(specs, errors):
        if get(r, "id") is not None and str(get(r, "id")) not in cat.pids:
            cat.add(r)
    if not cat.pids:
        sys.exit("No product records found in the files given. " + "; ".join(errors[:5]))

    # pass 2: score one product at a time, write a line each, keep only aggregates and the top N
    out = None
    if a.jsonl:
        out = sys.stdout if a.jsonl == "-" else open(a.jsonl, "w", encoding="utf-8")
    seen, top, n, total = set(), [], 0, 0
    bands = collections.Counter()
    gap_counts, gap_rev = collections.Counter(), collections.Counter()
    cats = collections.defaultdict(lambda: {"products": 0, "score": 0, "revenue": 0.0, "gaps": collections.Counter()})
    for label, r in iter_records(specs, []):
        pid = str(get(r, "id") or "")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        x = score_product(r, label, cat, perf, pct, queries, groups, a.min_desc)
        if out:
            out.write(json.dumps(x, ensure_ascii=False) + "\n")
        n += 1
        total += x["score"]
        bands["good" if x["score"] >= 80 else "fair" if x["score"] >= 60 else "poor"] += 1
        codes = {g["code"] for g in x["gaps"]}
        for c in codes:
            gap_counts[c] += 1
            gap_rev[c] += x["revenue"]
        c = cats[x["category"]]
        c["products"] += 1
        c["score"] += x["score"]
        c["revenue"] += x["revenue"]
        c["gaps"].update(codes)
        item = (x["priority"], -x["score"], n, x)
        if len(top) < a.top:
            heapq.heappush(top, item)
        elif item[:3] > top[0][:3]:
            heapq.heapreplace(top, item)
    if out and out is not sys.stdout:
        out.close()
    for path in spooled:
        os.unlink(path)
    results = [t[3] for t in sorted(top, key=lambda t: t[:3], reverse=True)]

    inconsist = []
    for field, cnt in cat.vocab.items():
        norm = collections.defaultdict(list)
        for v in cnt:
            norm[re.sub(r"[^a-z]", "", v.lower().replace("grey", "gray"))].append(v)
        inconsist += [{"field": field, "values": {v: cnt[v] for v in vs}} for vs in norm.values() if len(vs) > 1]
        if field == "colour":
            inconsist += [{"field": field, "values": {v: cnt[v]}, "note": "vague value"} for v in cnt if v.lower() in VAGUE]
    summary = {
        "schema": SCHEMA + "-summary", "version": VERSION,
        "products_audited": n,
        "average_score": round(total / n, 1),
        "bands": {"good (80+)": bands["good"], "fair (60-79)": bands["fair"], "poor (<60)": bands["poor"]},
        "with_performance_data": sum(1 for p in seen if p in perf),
        "common_gaps": [{"code": c, "gap": GAP_TEXT[c], "products": k, "share": round(k / n, 3),
                         "revenue_on_affected_products": round(gap_rev[c], 2)} for c, k in gap_counts.most_common()],
        "categories": sorted([{"category": k, "products": v["products"], "average_score": round(v["score"] / v["products"], 1),
                               "revenue": round(v["revenue"], 2), "top_gaps": [GAP_TEXT[g] for g, _ in v["gaps"].most_common(3)]}
                              for k, v in cats.items()], key=lambda c: (-c["revenue"], c["average_score"])),
        "boilerplate_templates": [{"products": k, "template_start": s[:100]} for s, k in cat.skel.most_common(5) if k >= cat.boiler_min],
        "fields_absent_everywhere": [f for f, present in (("gtin/mpn", cat.has_ident), ("image alt text", cat.has_alt),
                                                          ("availability", cat.has_avail)) if not present],
        "vocabulary_inconsistencies": inconsist[:20],
        "skipped_input": errors,
    }
    if perf_missing:
        summary["performance_rows_missing_values"] = {
            "rows": perf_missing, "note": "revenue or visits missing or not a number (e.g. NA); counted as 0"}
    for e in errors:
        print("SKIPPED " + e, file=sys.stderr)
    if not a.markdown:
        if a.jsonl != "-":
            json.dump({"summary": summary, "products": results}, sys.stdout, indent=2)
            print()
        return
    s = summary
    print(f"Audited {n} products; average score {s['average_score']}/100 "
          f"(good {bands['good']}, fair {bands['fair']}, poor {bands['poor']}). "
          f"{s['with_performance_data']} have performance data.\n")
    print("| Gap | Products | Share | Revenue on affected products |\n|---|---|---|---|")
    for g in s["common_gaps"][:12]:
        print(f"| {g['gap']} ({g['code']}) | {g['products']} | {g['share']:.0%} | ${g['revenue_on_affected_products']:,.0f} |")
    print("\n| Category | Products | Avg score | Revenue | Top gaps |\n|---|---|---|---|---|")
    for c in s["categories"][:15]:
        print(f"| {c['category']} | {c['products']} | {c['average_score']} | ${c['revenue']:,.0f} | {'; '.join(c['top_gaps'])} |")
    if s["boilerplate_templates"]:
        print("\nBoilerplate templates:")
        for b in s["boilerplate_templates"]:
            print(f"- {b['products']} products: \"{b['template_start']}...\"")
    if s["fields_absent_everywhere"]:
        print("\nFields absent from every product audited: " + ", ".join(s["fields_absent_everywhere"]))
    if s["vocabulary_inconsistencies"]:
        print("\nInconsistent values: " + "; ".join(
            f"{v['field']}: " + ", ".join(f"{k} ({c})" for k, c in v["values"].items()) for v in s["vocabulary_inconsistencies"][:8]))
    if errors:
        print(f"\nSkipped input: {len(errors)} (first: {errors[0]})")
    print("\n| # | Product | Category | Score | Revenue | Visits | Main gaps |\n|---|---|---|---|---|---|---|")
    for i, x in enumerate(results, 1):
        gaps = "; ".join(g["gap"] + (f" ({g['detail']})" if g["detail"] else "") for g in x["gaps"][:4])
        print(f"| {i} | {x['title'][:60]} ({x['pid']}) | {x['category']} | {x['score']} | ${x['revenue']:,.0f} | {x['visits']:,.0f} | {gaps} |")


if __name__ == "__main__":
    try:
        main()
    except ToolError as e:
        if "--markdown" in sys.argv[1:]:
            print(e, file=sys.stderr)
        else:
            print(json.dumps({"ok": False, "error": str(e)}), file=sys.__stdout__)
        sys.exit(1)
