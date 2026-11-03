"""Regenerates the synthetic fixtures in this folder: python3 tests/fixtures/discovery/product_visibility/make_fixtures.py"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def w(name, obj):
    with open(HERE / name, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=1)
        f.write("\n")


def summ(score, rel, perf, merch=None, kw=8.0, vec=0.3):
    s = {"totalNormalizedScore": score, "relevance": rel, "performance": perf, "keyword_score": kw, "vector_score": vec,
         "relevance_aware": {"relevance_aware_global": 0}, "semantic_weight": 0}
    if merch:
        s["merchandisingRulesApplied"] = merch
    return s


def fields(title_match=True):
    f = [{"match": True, "value": 2, "field": "BR_MV_ALL_text_tf", "term": "jacket", "boost": 1}]
    if title_match:
        f.append({"match": True, "value": 1, "field": "BR_SV_GENERAL_TERMV_product_name_tf", "term": "jacket", "boost": 1})
    return f


RULE = {"id": 900001, "ruleType": "ranking", "queries": [{"query": "rain jacket", "type": "sitesearch", "matchType": "EXACT_MATCH"}],
        "customizationItems": [
            {"type": "boost_top_products", "value": json.dumps([{"product_id": p, "product_name": "Boosted " + p} for p in ("A1", "A2", "A3")])},
            {"type": "explicit_filters", "value": json.dumps([{"rule": {"type": "clause", "operator": "AND", "operands": [
                {"type": "attribute", "operator": "OR", "name": "category", "operands": ["cat-x"]}], "strength": 0},
                "filter_type": "exclude"}])}],
        "liveInTest": False}
ALGO = {"id": 900002, "ruleType": "ranking_algo", "queries": [{"query": "*"}],
        "customizationItems": [{"type": "ranking_algo", "value": "{\"id\": \"br-fake\"}"}]}


def grid(docs, explain, start=0, total=60, rules=(RULE, ALGO), extra=None):
    data = {"response": {"numFound": total, "start": start, "docs": docs},
            "debug": {"explain.structured": explain, "customizations.explain": list(rules),
                      "feUrl": "http://frontend.example.invalid/api?auth_key=FAKEKEY", "sqApiUrl": "http://sq.example.invalid/?x=FAKE"},
            "did_you_mean": []}
    data.update(extra or {})
    return {"success": True, "data": data, "error": None, "environment_used": "production"}


def single(pid):
    docs = [{"pid": pid, "title": "Item " + pid, "docType": "product"}] if pid else []
    return grid(docs, {pid: fields() + [summ(10, 5, 5)]} if pid else {}, total=1 if pid else 0)


def main():
    # Page 1: A1-A3 boosted at the top, a banner row, then P01..P27. P05 is buried, P10 has a weak text match
    # (no title match), P12 has a weak performance score.
    docs, ex = [], {}
    for p in ("A1", "A2", "A3"):
        docs.append({"pid": p, "title": "Boosted rain jacket " + p, "docType": "product"})
        ex[p] = fields() + [summ(600, 90, 900, {"hardBoost": ["parent_product_id:" + p]})]
    docs.insert(2, {"docType": "content", "contentType": "banner_url", "content": "https://cdn.example.test/b.jpg", "slots": [3]})
    for i in range(1, 28):
        p = f"P{i:02d}"
        rel = 30.0 if p == "P10" else 88.0 - i * 0.1
        perf = 50.0 if p == "P12" else 500.0 - i
        merch = {"hardBury": ["parent_product_id:P05"]} if p == "P05" else None
        docs.append({"pid": p, "title": ("Wool coat " if p == "P10" else "Rain jacket ") + p, "docType": "product"})
        ex[p] = fields(p != "P10") + [summ(400 - i, rel, perf, merch)]
    w("grid_page1.json", grid(docs, ex, start=0, total=60))

    # Page 2 (start=30): P40 deep in the results.
    docs2, ex2 = [], {}
    for i in range(40, 45):
        p = f"P{i:02d}"
        docs2.append({"pid": p, "title": "Rain jacket " + p, "docType": "product"})
        ex2[p] = fields() + [summ(200 - i, 87.0, 300.0)]
    w("grid_page2.json", grid(docs2, ex2, start=30, total=60))

    # A plain grid with no ranking rules: Q30 ranks 30th with nothing holding it back.
    docs3, ex3 = [], {}
    for i in range(1, 31):
        p = f"Q{i:02d}"
        docs3.append({"pid": p, "title": "Rain jacket " + p, "docType": "product"})
        ex3[p] = fields() + [summ(400 - i, 88.0, 500.0 - i)]
    w("grid_plain.json", grid(docs3, ex3, total=30, rules=(ALGO,)))

    # A grid whose search was spell-corrected and redirects.
    w("grid_redirect.json", grid(docs3[:2], {k: ex3[k] for k in ("Q01", "Q02")}, total=2, rules=(ALGO,), extra={
        "autoCorrectQuery": "rain jacket",
        "keywordRedirect": {"original query": "rain jaket", "redirected query": "rain jacket",
                            "redirected url": "https://shop.example.test/rainwear"}}))

    w("match_check_found.json", single("P99"))
    w("match_check_empty.json", single(None))
    w("rules_off_found.json", single("P77"))
    w("rules_off_empty.json", single(None))
    w("lookup_found.json", single("P88"))
    w("lookup_empty.json", single(None))
    w("catalog_unavailable.json", {"result": {"success": True, "data": {"id": "P77", "attributes": {
        "availability": False, "title": "Linen shirt", "description": "A light linen shirt for summer.",
        "category_paths": [[{"id": "cat-top", "name": "tops"}, {"id": "cat-x", "name": "shirts"}]]}}, "error": None}})
    w("catalog_ok.json", {"result": {"success": True, "data": {"id": "P10", "attributes": {
        "availability": True, "title": "Wool coat", "description": "Warm and waterproof.",
        "category_paths": [[{"id": "cat-out", "name": "outerwear"}]]}}, "error": None}})
    w("error.json", {"result": {"success": False, "data": [], "error": "[ACCESS_DENIED] not allowed"}})


if __name__ == "__main__":
    main()
