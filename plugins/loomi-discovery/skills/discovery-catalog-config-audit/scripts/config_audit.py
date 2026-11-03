#!/usr/bin/env python3
"""Audit a Bloomreach Discovery catalog's attribute and index configuration: settings that quietly affect every query.

Usage:
  python3 config_audit.py --config config.json [--reserved reserved.json] [--products page1.json ...]
         [--catalogs catalogs.json] [--catalog NAME] [--today 2026-11-03] [--out audit.json]

--config     saved get_discovery_catalog_config result (required).
--reserved   saved get_discovery_catalog_reserved_attributes result: the names Bloomreach reserves.
--products   saved search_discovery_catalog_products list pages: a sample for fill rates (repeat per page).
--catalogs   saved search_discovery_catalogs list: index freshness and document counts.
--catalog    the catalog name to read from --catalogs (default: the only production catalog).
--today      the audit date (default: today in UTC); pass it to make results repeatable.

Prints JSON: findings sorted by priority (high, medium, low), each with the attribute, what's wrong, the fix to
make in the dashboard and a hand-off skill; an attribute table (level, data type, facetable, searchable,
displayable, sample fill rate); and what couldn't be checked. Attribute values are never printed, only names
and fill rates, so internal fields such as margin never leak.

Thresholds and word lists are in references/rules.json. Standard library only; no network access.
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# The thresholds live in references/rules.json, next to this script's folder.
RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
PRIORITIES = ("high", "medium", "low")


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def tool_error(err):
    """A Loomi Connect error safe to repeat. An unknown account_name makes some Discovery tools list every
    account the user can access, so an account error that looks like a list is replaced, never echoed."""
    text = str(err or "no error text")
    if "account" in text.lower() and text.count(",") >= 3:
        return ("Loomi Connect returned an error about the account name; it isn't repeated because it can list "
                "other accounts. Ask the user to check the account name.")
    return text[:200]


def read(path):
    """The payload of a saved result, with the {"result": ...} and {"data": ...} wrappers removed."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {tool_error(d.get('error'))} "
                 "This check couldn't run; don't treat it as 'nothing found'.")
    if isinstance(data, dict) and isinstance(data.get("result"), (dict, list)):
        data = data["result"]
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], (dict, list)):
        data = data["data"]
    return data


def as_dict(data, path, what):
    if not isinstance(data, dict):
        fail(f"{path}: expected {what} (an object), got {type(data).__name__}.")
    return data


def as_list(data, path, what):
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        fail(f"{path}: expected {what} (a list), got {type(data).__name__}.")
    return [r for r in data if isinstance(r, dict)]


def today_arg(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {text!r}")


def filled(v):
    return v not in (None, "", [], {}) and not (isinstance(v, str) and not v.strip())


def words(name):
    return set(re.findall(r"[a-z]+", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(name)).lower()))


def short(names):
    names = sorted(names)
    n = RULES["list_limit"]
    return ", ".join(names[:n]) + (f" and {len(names) - n} more" if len(names) > n else "")


class Report:
    def __init__(self):
        self.findings, self.not_checked = [], []

    def add(self, priority, check, attribute, issue, fix, hand_off=None):
        self.findings.append({"priority": priority, "check": check, "attribute": attribute, "issue": issue,
                              "fix": fix, "hand_off": hand_off})


# ----------------------------------------------------------------------------------------------
# Checks

def check_internal(rep, custom):
    internal = set(RULES["internal_words"])
    for name, a in sorted(custom.items()):
        if not words(name) & internal:
            continue
        exposed = [w for w, on in (("displayable", a.get("displayable") is True),
                                   ("facetable", a.get("facetable") not in (None, "off", False)),
                                   ("searchable", a.get("searchable") is True)) if on]
        if "displayable" in exposed or "facetable" in exposed:
            rep.add("high", "internal field exposed", name,
                    f"Looks like internal commercial data but is {' and '.join(exposed)}: displayable attributes are "
                    "returned in every API response, so shoppers can read them in the page source, and facetable "
                    "ones can appear as filters.",
                    "Set displayable off and facetable off (keep it for ranking only, if that's what it's for).",
                    "facet-optimizer")
        elif exposed:
            rep.add("medium", "internal field exposed", name, "Looks like internal commercial data but is searchable, "
                    "so queries can match its values.", "Set searchable off.")


def check_searchability(rep, cfg):
    reserved = cfg.get("reserved_attribute_searchability") or {}
    core = cfg.get("core_attribute_searchability") or {}
    for name, priority in RULES["must_be_searchable"].items():
        source = reserved if name in reserved else core if name in core else None
        if source is not None and source.get(name) is False:
            rep.add(priority, "key attribute not searchable", name,
                    f"{name} isn't searchable, so queries that use it can't match.",
                    f"Make {name} searchable in the catalog's attribute settings.", "discovery-search-health")
    numeric = sorted(n for n in RULES["numeric_reserved"] if reserved.get(n) is True)
    if numeric:
        rep.add("low", "numeric attribute searchable", short(numeric),
                "Numbers are searchable, so a query such as '70' matches every product with that value.",
                "Review: make them not searchable unless shoppers search by them.")


def check_custom_flags(rep, custom):
    numeric = sorted(n for n, a in custom.items() if a.get("data_type") == "number" and a.get("searchable") is True)
    if numeric:
        rep.add("medium", "numeric attribute searchable", short(numeric),
                "Number attributes are searchable, so short numeric queries match unrelated products.",
                "Set searchable off for these number attributes.")
    ids = sorted(n for n, a in custom.items() if words(n) & set(RULES["id_words"]) and a.get("searchable") is True)
    if ids:
        rep.add("low", "identifier searchable", short(ids),
                "Identifier attributes are searchable. Fine if shoppers search by code; noise otherwise.",
                "Review: keep searchable only if shoppers type these codes.")


def strip_prefix(name):
    low = name.lower()
    for p in RULES["reserved_prefixes"]:
        if low.startswith(p):
            low = low[len(p):]
    return low


def check_duplicates(rep, custom, reserved_names):
    for name in sorted(custom):
        base = strip_prefix(name)
        twin = next((r for r in (base, base.rstrip("s"), base + "s") if r in reserved_names and r != name), None)
        if twin and base != name.lower():
            rep.add("medium", "duplicates a reserved attribute", name,
                    f"{name} looks like a copy of the reserved attribute {twin}. Facets, rules and ranking can end up "
                    "using different ones, and merchandisers pick the wrong one.",
                    f"Use {twin} everywhere and stop sending {name}, or document why both exist.", "facet-optimizer")


def check_variants(rep, cfg, custom):
    v = cfg.get("variants") or {}
    if v.get("use_unavailable_variant_as_hero") is True:
        rep.add("medium", "variant settings", "variants.use_unavailable_variant_as_hero",
                "An out-of-stock variant can be shown as the product's hero, so shoppers see a colour or size they "
                "can't buy.", "Turn off 'use unavailable variant as hero' unless every variant is always in stock.")
    variant_facets = sorted(n for n, a in custom.items()
                            if a.get("level") == "variant" and a.get("facetable") not in (None, "off", False))
    if variant_facets and v.get("enable_filtering") is False:
        rep.add("low", "variant settings", short(variant_facets),
                "Variant-level attributes are facetable but variant filtering is off, so filtering on them may still "
                "show products whose matching variant isn't the one displayed.",
                "Review: enable variant filtering if shoppers filter on these.", "facet-optimizer")


def check_index(rep, cfg, catalog, today):
    idx = cfg.get("index") or {}
    threshold = idx.get("search_docs_drop_threshold")
    if isinstance(threshold, (int, float)) and threshold > RULES["max_drop_threshold"]:
        rep.add("medium", "index safety", "index.search_docs_drop_threshold",
                f"The drop threshold is {threshold}. If it's the percentage of products a feed may remove before "
                "indexing stops, a broken feed could empty search.", "Confirm what it means for this account, and "
                "lower it to a safe share (see max_drop_threshold).", "data-feed-health")
    if idx.get("enable_index_jobs") is False:
        rep.add("high", "index safety", "index.enable_index_jobs", "Index jobs are off, so catalog changes never "
                "reach search.", "Turn index jobs back on.", "data-feed-health")
    sug = cfg.get("autosuggest") or {}
    chars = sug.get("minimum_character_count")
    if isinstance(chars, (int, float)) and chars > RULES["max_suggest_min_chars"]:
        rep.add("low", "autosuggest", "autosuggest.minimum_character_count",
                f"Suggestions only start after {chars} characters.", "Lower it (see max_suggest_min_chars).",
                "autosuggest-audit")
    if catalog is None:
        return
    stats = catalog.get("stats") or {}
    if stats.get("product_doc_count") == 0:
        rep.add("high", "catalog", catalog.get("name"), "The production catalog has no products indexed.",
                "Check the latest feed and index jobs.", "data-feed-health")
    refreshed = stats.get("last_index_refresh_at")
    if refreshed:
        try:
            when = datetime.fromisoformat(str(refreshed).replace("Z", "+00:00")).date()
        except ValueError:
            fail(f"catalogs: last_index_refresh_at isn't a date ({str(refreshed)[:40]!r}).")
        age = (today - when).days
        if age > RULES["stale_index_days"]:
            rep.add("medium", "catalog", catalog.get("name"), f"The index was last refreshed {age} days ago.",
                    "Check why feed and index jobs stopped.", "data-feed-health")


def sample_fill(products, path):
    fill, n = {}, 0
    for p in products:
        attrs = p.get("attributes")
        if not isinstance(attrs, dict):
            fail(f"{path}: product {str(p.get('id'))[:40]!r} has no attributes object.")
        n += 1
        for k, v in attrs.items():
            fill[k] = fill.get(k, 0) + (1 if filled(v) else 0)
    return n, fill


def check_fill(rep, custom, reserved_names, n, fill, defaults):
    for name, priority in RULES["key_reserved"].items():
        share = fill.get(name, 0) / n
        if share < RULES["key_min_fill"]:
            rep.add(priority, "key attribute missing", name,
                    f"Only {share:.0%} of sampled products have {name}.",
                    "Fix the feed so every product sends it.", "product-data-audit")
    for name, a in sorted(custom.items()):
        share = fill.get(name, 0) / n
        if share < RULES["custom_min_fill"]:
            used = a.get("searchable") is True or a.get("facetable") not in (None, "off", False)
            what = "never filled" if share == 0 else f"filled on only {share:.0%} of sampled products"
            rep.add("medium" if used else "low", "configured but empty", name,
                    f"{name} is configured{' and used in search or facets' if used else ''} but {what}.",
                    "Send it in the feed, or remove it from the configuration.", "product-data-audit")
    known = set(custom) | set(reserved_names) | set(RULES["core_fields"])
    extra = sorted(k for k in fill if k not in known and fill[k] > 0)
    if extra:
        rep.add("low", "unconfigured attribute", short(extra),
                "These attributes arrive in the feed but have no configuration, so the defaults apply "
                f"(facetable {json.dumps(defaults.get('facetable', 'unknown'))}, "
                f"searchable {json.dumps(defaults.get('searchable', 'unknown'))}).",
                "Configure them if shoppers should search or filter on them; otherwise ignore.")


def attribute_table(custom, n, fill):
    return [{"name": name, "level": a.get("level"), "data_type": a.get("data_type"), "facetable": a.get("facetable"),
             "searchable": a.get("searchable"), "displayable": a.get("displayable"),
             "sample_fill": round(fill.get(name, 0) / n, 3) if n else None}
            for name, a in sorted(custom.items())]


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="saved get_discovery_catalog_config result")
    ap.add_argument("--reserved", help="saved get_discovery_catalog_reserved_attributes result")
    ap.add_argument("--products", action="append", default=[], help="saved search_discovery_catalog_products page")
    ap.add_argument("--catalogs", help="saved search_discovery_catalogs list")
    ap.add_argument("--catalog", help="catalog name to read from --catalogs")
    ap.add_argument("--today", type=today_arg, help="audit date YYYY-MM-DD (default: today in UTC)")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    today = a.today or datetime.now(timezone.utc).date()
    rep = Report()

    cfg = as_dict(read(a.config), a.config, "a catalog config")
    custom = cfg.get("custom_attributes")
    if not isinstance(custom, dict):
        fail(f"{a.config}: custom_attributes is missing or isn't an object; is this a get_discovery_catalog_config result?")
    custom = {k: v for k, v in custom.items() if isinstance(v, dict)}

    reserved_names = set()
    if a.reserved:
        data = as_dict(read(a.reserved), a.reserved, "reserved attributes")
        static = data.get("static_attributes_config", data)
        if not isinstance(static, dict):
            fail(f"{a.reserved}: static_attributes_config isn't an object.")
        reserved_names = set(static)
    else:
        rep.not_checked.append("Duplicates of reserved attributes and unconfigured feed attributes: no --reserved file.")

    catalog = None
    if a.catalogs:
        cats = as_list(read(a.catalogs), a.catalogs, "a catalog list")
        prod = [c for c in cats if c.get("environment", "production") == "production"
                and (a.catalog is None or c.get("name") == a.catalog)]
        if len(prod) == 1:
            catalog = prod[0]
        else:
            rep.not_checked.append("Index freshness: name the catalog with --catalog (several, or none, matched).")
    else:
        rep.not_checked.append("Index freshness and document counts: no --catalogs file.")

    check_internal(rep, custom)
    check_searchability(rep, cfg)
    check_custom_flags(rep, custom)
    if reserved_names:
        check_duplicates(rep, custom, reserved_names)
    check_variants(rep, cfg, custom)
    check_index(rep, cfg, catalog, today)

    n, fill = 0, {}
    for path in a.products:
        k, f = sample_fill(as_list(read(path), path, "a product list"), path)
        n += k
        for key, v in f.items():
            fill[key] = fill.get(key, 0) + v
    if n:
        check_fill(rep, custom, reserved_names, n, fill, cfg.get("custom_attributes_defaults") or {})
        if n < RULES["min_sample"]:
            rep.not_checked.append(f"Fill rates are rough: only {n} products sampled (see min_sample).")
    else:
        rep.not_checked.append("Fill rates: no --products sample.")
    rep.not_checked.append("Range facets: the catalog config has no range setting; check numeric facets with facet-optimizer.")

    findings = sorted(rep.findings, key=lambda f: (PRIORITIES.index(f["priority"]), f["check"], f["attribute"] or ""))
    out = {"ok": True, "today": today.isoformat(), "sampled_products": n,
           "counts": {p: sum(f["priority"] == p for f in findings) for p in PRIORITIES},
           "findings": findings, "attributes": attribute_table(custom, n, fill), "not_checked": rep.not_checked}
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
