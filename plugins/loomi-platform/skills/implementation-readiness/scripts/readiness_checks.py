#!/usr/bin/env python3
"""Build a go-live checklist for a new Bloomreach Discovery and Engagement implementation.

Usage:
  python3 readiness_checks.py [--stage prelaunch|live] [--scope discovery,engagement]
         [--pixel pixel_24h.json] [--catalog-config config.json] [--products products_p1.json ...]
         [--api search=api_search.json --api category=api_category.json]
         [--event-schema events.json] [--customer-schema ids.json] [--consent consent.json]
         [--catalogs catalogs.json] [--catalog-items items.json] [--scenarios scenarios.json ...]
         [--item extra_items.json ...] [--title "<account / project>"] [--today 2026-11-03] [--launch 2026-11-20]
         [--json] [--out checklist.md]

Inputs are raw Loomi Connect responses saved to files:
  --pixel            get_pixel_health_status (24 or 168 hours)
  --catalog-config   get_discovery_catalog_config
  --products         search_discovery_catalog_products list pages (a sample of products)
  --api NAME=FILE    get_discovery_api_requests with the filter for NAME in references/rules.json
  --event-schema     get_event_schema
  --customer-schema  get_customer_schema
  --consent          get_consent_settings
  --catalogs         search_catalogs (list)
  --catalog-items    search_catalog_items for the product catalog (its total)
  --scenarios        search_scenarios list pages, all statuses
  --item FILE        a JSON list of checked items from other skills (data-feed-health, engagement-tracking-health):
                     {"area", "check", "status", "evidence", "fix", "owner"}

Each check gets RED, AMBER, GREEN or NOT CHECKED, with evidence, the fix and an owner (developer, merchandiser
or CRM). Inputs not given are NOT CHECKED. Prints a Markdown checklist, blockers first, with a verdict:
NOT READY, READY WITH FIXES, INCOMPLETE or READY (or JSON with --json).

Rules: references/rules.json. Standard library only; no network access.
"""
import argparse
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
AREAS = ["Discovery tracking", "Discovery catalog", "Discovery search", "Engagement tracking",
         "Engagement identity and consent", "Engagement catalog", "Engagement flows"]
STATUSES = ("RED", "AMBER", "GREEN", "NOT CHECKED")
MISSING = {"", "na", "n/a", "-", "null", "none", "nan"}
OWN = RULES["owners"]


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


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


def load(path, keep=()):
    """A saved tool result's data, unwrapping {"result": ...} and {"data": ...} unless the layer has a `keep` key."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    while isinstance(data, dict):
        if data.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {str(data.get('error') or 'no error text')[:200]} "
                 "This check couldn't run; don't treat it as 'nothing found'.")
        if any(k in data for k in keep):
            break
        if "result" in data and isinstance(data["result"], (dict, list)):
            data = data["result"]
        elif "data" in data and isinstance(data["data"], (dict, list)):
            data = data["data"]
        else:
            break
    return data


def pair(text):
    """NAME=FILE, split on the first "="."""
    name, sep, path = text.partition("=")
    if not sep or not name.strip() or not path.strip():
        raise argparse.ArgumentTypeError(f"expected NAME=FILE, got {text!r}")
    return name.strip(), path.strip()


def item(area, check, status, evidence, fix="—", owner="—"):
    return {"area": area, "check": check, "status": status, "evidence": evidence, "fix": fix, "owner": owner}


def no_traffic_status(stage):
    return "AMBER" if stage == "prelaunch" else "RED"


def fmt(n):
    return f"{int(n):,}" if float(n).is_integer() else f"{n:,.1f}"


# ---------------------------------------------------------------------------------------------
# Discovery

def check_pixel(path, stage):
    d = load(path, keep=("page_view_pixels", "event_pixels"))
    if not isinstance(d, dict) or not ({"page_view_pixels", "event_pixels"} & set(d)):
        fail(f"{path}: no page_view_pixels or event_pixels found; is this a get_pixel_health_status result?")
    types = {}
    for p in (d.get("page_view_pixels") or []) + (d.get("event_pixels") or []):
        types[p.get("display_type")] = p
    hours = d.get("period_hours")
    window = f"{hours}h" if hours else "the window"
    out = []
    for t in RULES["pixel_launch_types"]:
        p = types.get(t) or {}
        n = number(p.get("event_count")) or 0
        if n > 0:
            rate = number(p.get("issue_rate_pct")) or 0
            out.append(item("Discovery tracking", f"pixel {t}", "GREEN",
                            f"{fmt(n)} events in {window}, {rate:g}% flagged (rate issues with data-feed-health)"))
        else:
            out.append(item("Discovery tracking", f"pixel {t}", no_traffic_status(stage),
                            f"no events in {window}" + ("" if p else " (type not reported)"),
                            f"Add or fix the {t} pixel on its pages, then check it in debug mode", OWN["pixel"]))
    used = [t for t in RULES["pixel_optional_types"] if (number((types.get(t) or {}).get("event_count")) or 0) > 0]
    unused = [t for t in RULES["pixel_optional_types"] if t not in used]
    out.append(item("Discovery tracking", "optional pixel types", "GREEN",
                    f"in use: {', '.join(used) or 'none'}; not in use: {', '.join(unused) or 'none'}",
                    "Add the ones for features the site uses (autosuggest, widgets)" if unused else "—", OWN["pixel"]))
    return out


def check_catalog_config(path):
    d = load(path, keep=("custom_attributes", "reserved_attribute_searchability"))
    if not isinstance(d, dict) or "custom_attributes" not in d and "reserved_attribute_searchability" not in d:
        fail(f"{path}: no attribute settings found; is this a get_discovery_catalog_config result?")
    out = []
    reserved = d.get("reserved_attribute_searchability") or {}
    for names, bad in ((RULES["searchable_red"], "RED"), (RULES["searchable_amber"], "AMBER")):
        for a in names:
            if reserved.get(a) is True:
                out.append(item("Discovery catalog", f"{a} searchable", "GREEN", "searchable"))
            else:
                out.append(item("Discovery catalog", f"{a} searchable", bad,
                                "not searchable" if a in reserved else "not in the reserved attribute settings",
                                f"Make {a} searchable in the catalog attribute settings", OWN["attributes"]))
    core = d.get("core_attribute_searchability") or {}
    if core.get("category_names") is False:
        out.append(item("Discovery catalog", "category names searchable", "AMBER", "not searchable",
                        "Make category names searchable so 'boots' matches the Boots category", OWN["attributes"]))
    custom = d.get("custom_attributes") or {}
    facetable = sorted(k for k, v in custom.items() if isinstance(v, dict) and str(v.get("facetable")).lower() in ("auto", "manual"))
    searchable = sum(1 for v in custom.values() if isinstance(v, dict) and v.get("searchable") is True)
    status = "GREEN" if len(facetable) >= RULES["min_facetable_custom_attributes"] else "AMBER"
    out.append(item("Discovery catalog", "facetable attributes", status,
                    f"{len(facetable)} of {len(custom)} custom attributes facetable"
                    + (f" (e.g. {', '.join(facetable[:5])})" if facetable else "") + f"; {searchable} searchable",
                    "—" if status == "GREEN" else "Set the attributes shoppers filter by (size, colour, material) to facetable",
                    OWN["attributes"]))
    return out


def check_products(paths):
    recs = []
    for p in paths:
        d = load(p)
        rows = d if isinstance(d, list) else [d]
        recs += [r for r in rows if isinstance(r, dict)]
    if not recs:
        fail("--products: no product records found; are these search_discovery_catalog_products list pages?")
    out = []
    n = len(recs)
    for field, names in RULES["discovery_product_fields"].items():
        filled = 0
        for r in recs:
            attrs = r.get("attributes") or r
            vals = [attrs.get(k) for k in names]
            v = next((x for x in vals if x not in (None, "", [], {}) and not (isinstance(x, str) and x.strip().lower() in MISSING)), None)
            if field == "price" and number(v) is None:
                v = None
            filled += v is not None
        share = filled / n
        required = field in RULES["discovery_required_fields"]
        if share < RULES["field_fill_red"] and required:
            status = "RED"
        elif share < RULES["field_fill_amber"]:
            status = "AMBER"
        else:
            status = "GREEN"
        out.append(item("Discovery catalog", f"product {field} filled", status,
                        f"{filled} of {n} sampled products ({share * 100:.0f}%)"
                        + (" with a numeric price (needed to sort and filter by price)" if field == "price" else ""),
                        "—" if status == "GREEN" else f"Fill {field} for every product in the feed", OWN["feed"]))
    return out


def check_api(pairs, stage):
    out = []
    for name, path in pairs:
        d = load(path, keep=("results",))
        body = d.get("body", d) if isinstance(d, dict) else {}
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            fail(f"{path}: no results list found; is this a get_discovery_api_requests result?")
        total = sum(number(((r.get("total") or {}).get("request_count") or {}).get("value")) or 0 for r in results)
        days = len(results)
        if total > 0:
            out.append(item("Discovery search", f"{name} API traffic", "GREEN", f"{fmt(total)} requests over {days} days"))
        else:
            out.append(item("Discovery search", f"{name} API traffic", no_traffic_status(stage),
                            f"no {name} requests over {days} days",
                            f"Call the {name} API from the site (or staging) and check it returns results", OWN["api"]))
    return out


# ---------------------------------------------------------------------------------------------
# Engagement

def event_properties(event):
    props = event.get("properties")
    names = set()
    groups = props.values() if isinstance(props, dict) else [props]
    for g in groups:
        rows = g.get("properties") if isinstance(g, dict) else g
        if isinstance(rows, list):
            for p in rows:
                if isinstance(p, dict) and (p.get("property") or p.get("name")):
                    names.add(str(p.get("property") or p.get("name")).lower())
    return names


def check_events(path, stage):
    d = load(path, keep=("events",))
    events = d.get("events") if isinstance(d, dict) else None
    if not isinstance(events, list):
        fail(f"{path}: no events list found; is this a get_event_schema result?")
    by_type = {str(e.get("type")).lower(): e for e in events if isinstance(e, dict) and e.get("type")}
    out = []
    for name, spec in RULES["engagement_core_events"].items():
        found = next((a for a in spec["aliases"] if a.lower() in by_type), None)
        if not found:
            out.append(item("Engagement tracking", f"event {name}", "RED" if spec["required"] else "AMBER",
                            f"no {' / '.join(spec['aliases'])} event in the schema",
                            f"Track {name} from the website or app (SDK or API)", OWN["events"]))
            continue
        e = by_type[found.lower()]
        label = name if found == name else f"{name} (as {found})"
        if e.get("used") is False:
            out.append(item("Engagement tracking", f"event {label}", no_traffic_status(stage),
                            "defined but never received", f"Send {found} from the site and check it arrives", OWN["events"]))
            continue
        missing = [p for p in spec["properties"] if p.lower() not in event_properties(e)]
        if missing:
            out.append(item("Engagement tracking", f"event {label}", "AMBER",
                            f"received; missing properties: {', '.join(missing)}",
                            f"Add {', '.join(missing)} to {found}", OWN["events"]))
        else:
            out.append(item("Engagement tracking", f"event {label}", "GREEN",
                            "received, with " + (", ".join(spec["properties"]) if spec["properties"] else "the event itself")
                            + " (check volumes with engagement-tracking-health)"))
    return out


def check_ids(path):
    d = load(path)
    ids = d if isinstance(d, list) else (d.get("ids") if isinstance(d, dict) else None)
    if not isinstance(ids, list):
        fail(f"{path}: no identifier list found; is this a get_customer_schema result?")
    hard = [str(i.get("name")) for i in ids if isinstance(i, dict) and str(i.get("type")).lower() == "hard"]
    soft = [str(i.get("name")) for i in ids if isinstance(i, dict) and str(i.get("type")).lower() == "soft"]
    if hard:
        return [item("Engagement identity and consent", "customer IDs", "GREEN",
                     f"hard IDs: {', '.join(hard)}; soft IDs: {', '.join(soft) or 'none'}. Check the site identifies "
                     "customers with the hard ID on login and purchase")]
    return [item("Engagement identity and consent", "customer IDs", "RED",
                 f"no hard (permanent) ID; soft IDs: {', '.join(soft) or 'none'}",
                 "Set up a hard customer ID (such as registered or email_id) and identify customers on login and purchase",
                 OWN["identity"])]


def check_consent(path):
    d = load(path, keep=("categories",))
    if not isinstance(d, dict) or "categories" not in d:
        fail(f"{path}: no consent categories found; is this a get_consent_settings result?")
    cats = [c for c in d.get("categories") or [] if isinstance(c, dict)]
    names = [str(c.get("id")) for c in cats]
    if not cats:
        return [item("Engagement identity and consent", "consent categories", "RED", "no consent categories defined",
                     "Define consent categories (for example newsletter, SMS) and collect consent at sign-up", OWN["consent"])]
    general = d.get("general_consent") or {}
    note = "; email can be sent without a consent category" if general.get("email") is True else ""
    return [item("Engagement identity and consent", "consent categories", "GREEN",
                 f"{len(cats)} defined ({', '.join(names[:6])}){note}")]


def check_catalogs(path, items_path):
    d = load(path)
    cats = d if isinstance(d, list) else []
    product = [c for c in cats if isinstance(c, dict) and (c.get("is_product_catalog") is True or c.get("type") == "product")]
    out = []
    if product:
        out.append(item("Engagement catalog", "product catalog", "GREEN",
                        f"{len(product)} product catalog(s): {', '.join(str(c.get('name')) for c in product[:3])}"
                        + "; check freshness with data-feed-health"))
    else:
        out.append(item("Engagement catalog", "product catalog", "RED",
                        f"{len(cats)} catalog(s), none marked as a product catalog",
                        "Import the product catalog and mark it as the product catalog", OWN["catalog"]))
    if items_path:
        raw = load(items_path, keep=("total",))
        total = number(raw.get("total")) if isinstance(raw, dict) else None
        if total is None and isinstance(raw, dict):
            total = number(raw.get("matched"))
        if total is None:
            fail(f"{items_path}: no total found; is this a search_catalog_items result?")
        out.append(item("Engagement catalog", "catalog items", "GREEN" if total > 0 else "RED",
                        f"{fmt(total)} items", "—" if total > 0 else "Run the catalog import", OWN["catalog"]))
    return out


def check_flows(paths):
    recs = []
    for p in paths:
        d = load(p)
        recs += [r for r in (d if isinstance(d, list) else []) if isinstance(r, dict)]
    out = []
    for label, words, need_all in (("welcome flow", RULES["welcome_flow_words"], False),
                                   ("cart abandonment flow", RULES["cart_flow_words"], True)):
        def hit(name):
            n = str(name or "").lower()
            return all(w in n for w in words) if need_all else any(w in n for w in words)
        found = [r for r in recs if hit(r.get("name")) and not r.get("archived")]
        active = [r for r in found if str(r.get("status")).lower() == "active"]
        if active:
            out.append(item("Engagement flows", label, "GREEN",
                            f"active: {', '.join(str(r.get('name'))[:60] for r in active[:3])}"))
        elif found:
            states = sorted({str(r.get("status")) for r in found})
            out.append(item("Engagement flows", label, RULES["inactive_flow_status"],
                            f"{len(found)} found, none active ({', '.join(states)})",
                            f"QA it (scenario-qa) and start it at launch", OWN["flows"]))
        else:
            out.append(item("Engagement flows", label, RULES["missing_flow_status"],
                            f"no scenario named like a {label} among {len(recs)}",
                            f"Build a {label} (engagement-scenario-builder), or tell us its name if it's named differently",
                            OWN["flows"]))
    return out


# ---------------------------------------------------------------------------------------------

def area_key(i):
    a = i.get("area")
    return AREAS.index(a) if a in AREAS else len(AREAS)


def render(items, title, stage, today, launch):
    red = sorted([i for i in items if i["status"] == "RED"], key=area_key)
    amber = sorted([i for i in items if i["status"] == "AMBER"], key=area_key)
    green = [i for i in items if i["status"] == "GREEN"]
    unchecked = [i for i in items if i["status"] not in ("RED", "AMBER", "GREEN")]
    verdict = "NOT READY" if red else "READY WITH FIXES" if amber else "INCOMPLETE" if (unchecked or not green) else "READY"
    lines = [f"## Go-live readiness: {title}",
             f"Checked {today.isoformat()} ({stage})" + (f"; launch {launch.isoformat()}, {(launch - today).days} days to go" if launch else "") + ".",
             "",
             f"**Verdict:** {verdict}: {len(red)} blocker(s), {len(amber)} amber, {len(green)} green, {len(unchecked)} not checked.",
             ""]

    def cell(v):
        return str(v).replace("|", "/").replace("\n", " ")

    def table(rows, heading):
        if not rows:
            return
        lines.append(f"### {heading}")
        lines.append("| # | Area | Check | Evidence | Fix | Owner |")
        lines.append("|---|---|---|---|---|---|")
        for n, i in enumerate(rows, 1):
            lines.append(f"| {n} | {cell(i['area'])} | {cell(i['check'])} | {cell(i['evidence'])} | {cell(i['fix'])} | {cell(i['owner'])} |")
        lines.append("")

    table(red, "Blockers (fix before go-live)")
    table(amber, "Amber (fix or accept)")
    if green:
        lines.append("### Green")
        by_area = {}
        for i in green:
            by_area.setdefault(i["area"], []).append(i["check"])
        for a in sorted(by_area, key=lambda x: AREAS.index(x) if x in AREAS else len(AREAS)):
            lines.append(f"- **{a}:** {'; '.join(by_area[a])}")
        lines.append("")
    if unchecked:
        lines.append("**Not checked:** " + "; ".join(f"{i['area']}: {i['check']} ({i['evidence']})" for i in unchecked))
    owners = {}
    for i in red + amber:
        owners.setdefault(i["owner"], 0)
        owners[i["owner"]] += 1
    if owners:
        lines.append("**By owner:** " + ", ".join(f"{o} {n}" for o, n in sorted(owners.items())))
    return verdict, "\n".join(lines) + "\n"


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=("prelaunch", "live"), default=RULES["default_stage"], help="prelaunch: no traffic yet is AMBER; live: it is RED (default: rules.json)")
    ap.add_argument("--scope", default="discovery,engagement", help="discovery, engagement or both, comma-separated")
    ap.add_argument("--pixel", help="get_pixel_health_status result")
    ap.add_argument("--catalog-config", help="get_discovery_catalog_config result")
    ap.add_argument("--products", action="append", default=[], help="search_discovery_catalog_products list page (repeatable)")
    ap.add_argument("--api", action="append", default=[], type=pair, help="NAME=FILE: get_discovery_api_requests for search or category (repeatable)")
    ap.add_argument("--event-schema", help="get_event_schema result")
    ap.add_argument("--customer-schema", help="get_customer_schema result")
    ap.add_argument("--consent", help="get_consent_settings result")
    ap.add_argument("--catalogs", help="search_catalogs list result")
    ap.add_argument("--catalog-items", help="search_catalog_items result for the product catalog (its total)")
    ap.add_argument("--scenarios", action="append", default=[], help="search_scenarios list page, all statuses (repeatable)")
    ap.add_argument("--item", action="append", default=[], help="JSON list of checked rows from other skills (repeatable)")
    ap.add_argument("--title", default="this implementation", help="account and project, for the heading")
    ap.add_argument("--today", help="YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--launch", help="YYYY-MM-DD go-live date, to print days to go")
    ap.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    ap.add_argument("--out", help="write the checklist here instead of printing it")
    a = ap.parse_args()

    scope = {s.strip().lower() for s in a.scope.split(",") if s.strip()}
    if not scope <= {"discovery", "engagement"} or not scope:
        fail("--scope takes discovery, engagement or both, comma-separated.")
    try:
        today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(dt.timezone.utc).date()
        launch = dt.date.fromisoformat(a.launch) if a.launch else None
    except ValueError as e:
        fail(f"--today and --launch must be dates like 2026-11-20 ({e}).")

    items = []
    if "discovery" in scope:
        items += check_pixel(a.pixel, a.stage) if a.pixel else [
            item("Discovery tracking", "pixel event types", "NOT CHECKED", "no get_pixel_health_status result given")]
        items += check_catalog_config(a.catalog_config) if a.catalog_config else [
            item("Discovery catalog", "attribute settings", "NOT CHECKED", "no get_discovery_catalog_config result given")]
        items += check_products(a.products) if a.products else [
            item("Discovery catalog", "product fields", "NOT CHECKED", "no product sample given")]
        if a.api:
            items += check_api(a.api, a.stage)
        else:
            items.append(item("Discovery search", "search and category API traffic", "NOT CHECKED",
                              "no get_discovery_api_requests result given"))
    if "engagement" in scope:
        items += check_events(a.event_schema, a.stage) if a.event_schema else [
            item("Engagement tracking", "core events", "NOT CHECKED", "no get_event_schema result given")]
        items += check_ids(a.customer_schema) if a.customer_schema else [
            item("Engagement identity and consent", "customer IDs", "NOT CHECKED", "no get_customer_schema result given")]
        items += check_consent(a.consent) if a.consent else [
            item("Engagement identity and consent", "consent categories", "NOT CHECKED", "no get_consent_settings result given")]
        items += check_catalogs(a.catalogs, a.catalog_items) if a.catalogs else [
            item("Engagement catalog", "product catalog", "NOT CHECKED", "no search_catalogs result given")]
        items += check_flows(a.scenarios) if a.scenarios else [
            item("Engagement flows", "welcome and cart abandonment flows", "NOT CHECKED", "no search_scenarios result given")]

    extra = []
    for path in a.item:
        d = load(path)
        if not isinstance(d, list):
            fail(f"{path}: expected a JSON list of items.")
        for i in d:
            if not isinstance(i, dict):
                continue
            status = str(i.get("status") or "NOT CHECKED").strip().upper()
            extra.append(item(str(i.get("area") or "Other"), str(i.get("check") or ""),
                              status if status in STATUSES else "NOT CHECKED", str(i.get("evidence") or ""),
                              str(i.get("fix") or "—"), str(i.get("owner") or "—")))
    items += extra
    text_all = " ".join((i["area"] + " " + i["check"]).lower() for i in extra)
    if "discovery" in scope and not re.search(r"feed|index", text_all):
        items.append(item("Discovery catalog", "feed and index jobs", "NOT CHECKED",
                          "run data-feed-health's catalog check and pass its rows with --item"))
    if "discovery" in scope and not re.search(r"issue", text_all):
        items.append(item("Discovery tracking", "pixel issue rates", "NOT CHECKED",
                          "rate them with data-feed-health's pixel check and pass its rows with --item"))

    verdict, md = render(items, a.title, a.stage, today, launch)
    text = json.dumps({"ok": True, "verdict": verdict, "stage": a.stage, "items": items}, indent=2,
                      ensure_ascii=False) + "\n" if a.json else md
    if a.out:
        try:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        except OSError as e:
            fail(f"{a.out}: can't write it ({e}).")
        print(json.dumps({"ok": True, "out": a.out, "verdict": verdict}))
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
