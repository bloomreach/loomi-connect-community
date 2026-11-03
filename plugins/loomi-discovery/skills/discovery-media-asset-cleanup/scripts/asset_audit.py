#!/usr/bin/env python3
"""Find Bloomreach Discovery media assets and media rule placements that need cleaning up.

Usage:
  python3 asset_audit.py --assets assets_p0.json [--assets assets_p1.json ...]
         --rules site_media.json --rules category_media.json --rules global_media.json
         --details rule_2305338.json [--details ...] [--multi-slot multi_slot.json]
         [--today 2026-11-03] [--out audit.json]

--assets: saved search_discovery_assets list pages (fetch every page), or single-asset details.
--rules: saved list_site_search_media_rules / list_category_media_rules / list_global_media_rules pages.
--details: saved get_discovery_media_rule results, one per rule (a file may also hold a JSON list of them).
--multi-slot: the saved get_discovery_multi_slot_customizations result.

Prints JSON: each asset with where it's used (live, inactive only, unused), its findings, and a priority;
each rule's placement findings; the URLs worth loading (links_to_load: `url` to load, `shown` to put in the report,
`head_only` for links that carry a token); and what couldn't be checked, including Bloomreach app URLs, which are
never loaded.
Thresholds and word lists are in references/rules.json. Standard library only; no network access.
Editor names and email addresses in the inputs are never copied to the output.
"""
import argparse
import ipaddress
import json
import re
import sys
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

# The thresholds live in references/rules.json, next to this script's folder.
RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
ORDER = {"high": 0, "medium": 1, "low": 2}
URL_TYPES = {"image_url", "image_upload"}


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def tool_error(text):
    """A Loomi Connect error that's safe to repeat. An unknown account name can make a Discovery tool list every
    account the user can access, many of them other customers, so that kind of error is never echoed."""
    text = str(text or "no error text")
    if "account" in text.lower():  # these errors can list every account the user can access
        return ("Loomi Connect returned an error about the account name; it isn't repeated because it can list other "
                "accounts. Ask the user to check the account name.")
    return text[:200]


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {tool_error(d.get('error'))} "
                 "This check couldn't run; don't treat it as 'nothing found'.")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    return data


def records(path):
    """The list of records in a saved list result (or one record from a detail result)."""
    data = load(path)
    if isinstance(data, list):  # a list of records, or of saved detail results
        out = []
        for item in data:
            if isinstance(item, dict) and "success" in item and "data" in item:
                if item.get("success") is False:
                    fail(f"{path}: one of the saved results is a Loomi Connect error: {tool_error(item.get('error'))}")
                item = item["data"]
            if isinstance(item, dict):
                out.append(item)
        return out
    inner = data.get("data", data) if isinstance(data, dict) else data
    if isinstance(inner, dict):
        return [inner]
    return inner or []


def when(v):
    """Epoch milliseconds or an ISO date -> aware datetime; None when missing. Raises ValueError when unreadable."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
    t = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k in ("href", "src") and v:
                self.urls.append(v.strip())


def host_matches(host, domains):
    return any(host == d or host.endswith("." + d) for d in domains)


SENSITIVE = re.compile(r"([?&;](?:[^=&;#\s]*(?:%s)[^=&;#\s]*)=)[^&;#\s\"'<>]*" % "|".join(RULES["redact_param_words"]),
                       re.I)
USERINFO = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/\s@]+@", re.I)


def redact(text):
    """Text that's safe to show: user info and the values of email, token, key and similar URL parameters removed."""
    return SENSITIVE.sub(r"\1[redacted]", USERINFO.sub(r"\1[redacted]@", str(text)))


def is_internal(host):
    """True for an IP-literal host or a loopback, private or local name: never loaded from the user's machine."""
    host = host.strip("[]")
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa"))


def is_app_url(host, path):
    """A Bloomreach app or dashboard page (as opposed to a public CDN image): never loaded."""
    return host_matches(host, RULES["app_hosts"]) or (
        host_matches(host, RULES["bloomreach_hosts"]) and re.match(r"/p/[^/]+", path or "") is not None)


def url_findings(url, what, add, skipped=None):
    """Static checks on one URL. Returns "load", "head" (load with HEAD only: it carries a token) or None (don't load).
    Bloomreach app URLs are added to skipped, to be reported as not checked."""
    u = (url or "").strip()
    low = u.lower()
    if not u or u == "#":
        add("medium", "empty_link", f"{what} is empty")
        return None
    if low.startswith(("mailto:", "tel:")):
        return None
    if not re.match(r"[a-z][a-z0-9+.-]*:", low):
        add("medium", "missing_scheme", f"{what} has no https:// so browsers treat it as a relative link", u)
        return None
    if not low.startswith(("http://", "https://")):
        add("medium", "non_web_link", f"{what} isn't a web address", u)
        return None
    try:
        p = urlsplit(u)
        host = (p.hostname or "").lower()
        has_userinfo = p.username is not None or p.password is not None
    except ValueError:
        add("medium", "malformed_link", f"{what} isn't a valid URL", u)
        return None
    if has_userinfo:
        add("medium", "credentials_in_url", f"{what} has a username or password in it; remove them", u)
        return None
    if is_internal(host):
        add("medium", "internal_host", f"{what} points at an IP address or an internal host, which shoppers can't "
            "reach; it isn't loaded from your machine", u)
        return None
    if low.startswith("http://"):
        add("medium", "no_tls", f"{what} uses http://; browsers block or warn on it on an https site", u)
    if host_matches(host, RULES["placeholder_hosts"]):
        add("high", "placeholder_link", f"{what} points at a placeholder host", u)
        return None
    words = sorted(set(RULES["placeholder_words"]) & set(re.split(r"[^a-z0-9]+", (p.path + " " + p.query).lower())))
    if words:
        add("medium", "placeholder_words", f"{what} looks like a placeholder ({', '.join(words)}); confirm the real URL", u)
    if is_app_url(host, p.path):
        if skipped is not None:
            skipped.append(redact(u))
        return None
    names = [k.lower() for k in re.findall(r"(?:^|[&;])([^=&;]+)=", p.query)]
    return "head" if any(w in k for k in names for w in RULES["token_param_words"]) else "load"


def parse_shared(raw):
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except ValueError:
        return None


def asset_checks(asset, skipped):
    """Content findings for one asset, and the URLs it shows or links to, as (kind, url, method)."""
    found, urls = [], []

    def add(sev, check, issue, evidence=None):
        f = {"severity": sev, "check": check, "issue": issue}
        if evidence:
            f["evidence"] = redact(evidence)[:200]
        found.append(f)

    def check(url, what, kind):
        method = url_findings(url, what, add, skipped)
        if method:
            urls.append((kind, url.strip(), method))

    shared = parse_shared(asset.get("sharedData"))
    if shared is None:
        add("medium", "unreadable", "The asset's content (sharedData) isn't valid JSON")
        return found, urls
    dtype = asset.get("dataType")
    if dtype == "banners":
        banner = shared.get("banner") or {}
        btype = banner.get("bannerType")
        content = ((shared.get("image_url") or {}).get("imageUrl") or "").strip()
        if banner.get("enabled") is False:
            add("low", "asset_disabled", "The asset is switched off")
        if btype in URL_TYPES:
            before = len(urls)
            check(content, "Image URL", "image")
            if len(urls) > before:
                host = (urlsplit(content).hostname or "").lower()
                if not host_matches(host, RULES["bloomreach_hosts"]):
                    add("low", "hotlinked_image", f"Image is hot-linked from {host}, which can change or remove it; "
                        "upload it to Bloomreach instead", content)
        elif btype == "banner_url":
            if not re.match(r"https?://", content, re.I):
                add("medium", "not_a_url", "A banner URL asset holds text, not a URL", content)
            else:
                check(content, "Banner URL", "link")
        elif btype == "html":
            if not content:
                add("medium", "empty_content", "The HTML asset is empty")
            parser = Links()
            parser.feed(content)
            for u in parser.urls:
                check(u, "Link or image in the HTML", "link")
        else:
            add("low", "unknown_type", f"Unknown banner type {btype!r}; check it by hand")
        for h in shared.get("banner_hotspot") or []:
            if not h.get("url"):
                add("medium", "hotspot_without_link", "A clickable hotspot has no link")
            else:
                check(h["url"], "Hotspot link", "link")
            if h.get("url") and not h.get("altText"):
                add("low", "hotspot_alt", "A hotspot has no alt text, so screen readers can't describe the link")
    elif dtype == "weblayer":
        for page in (shared.get("trigger") or {}).get("include_pages") or []:
            u = page.get("url") or ""
            if re.match(r"https?://", u, re.I):
                url_findings(u, "Weblayer page targeting", add, [])
    return found, urls


def placement_checks(detail, add):
    items = (detail.get("customizationItems") or {}).get("content_in_grid") or []
    seen = {}
    for it in items:
        slots = it.get("slots") or []
        name = it.get("bannerName") or it.get("bannerId")
        if not it.get("bannerId"):
            add("medium", "empty_placement", f"A grid placement has no asset", str(slots))
        if not slots:
            add("medium", "empty_placement", f"Grid placement '{name}' has no slots")
            continue
        if any(not isinstance(s, int) or s < 1 or s > RULES["max_grid_slot"] for s in slots):
            add("medium", "slot_out_of_range", f"Grid placement '{name}' uses a slot outside 1-{RULES['max_grid_slot']}", str(slots))
        if len(set(slots)) != len(slots):
            add("medium", "duplicate_slot", f"Grid placement '{name}' lists the same slot twice", str(slots))
        dim = re.fullmatch(r"(\d+)x(\d+)", str(it.get("dimension") or ""))
        expected = int(dim.group(1)) * int(dim.group(2)) if dim else 1 if it.get("slotType") != "multi" else None
        if it.get("slotType") == "multi" and not dim:
            add("medium", "multi_slot_shape", f"Multi-slot placement '{name}' has no dimension")
        elif expected and len(slots) != expected:
            add("medium", "multi_slot_shape", f"Placement '{name}' is {it.get('dimension') or 'single'} but covers "
                f"{len(slots)} slot(s)", str(slots))
        if len(slots) > RULES["max_slots_per_placement"]:
            add("medium", "multi_slot_shape", f"Placement '{name}' spans more than {RULES['max_slots_per_placement']} slots")
        for s in slots:
            if s in seen and seen[s] != name:
                add("high", "overlapping_slots", f"Slot {s} is used by both '{seen[s]}' and '{name}'")
            seen.setdefault(s, name)


def referenced_ids(detail):
    """Every asset ID a media rule detail points at: the top banner, grid placements and sharedId."""
    ids = set()
    items = detail.get("customizationItems") or {}
    top = items.get("campaign") or {}
    if top.get("bannerId"):
        ids.add(top["bannerId"])
    for it in items.get("content_in_grid") or []:
        if it.get("bannerId"):
            ids.add(it["bannerId"])
    if detail.get("sharedId"):
        ids.add(detail["sharedId"])
    return {int(i) for i in ids if str(i).isdigit()}


def day(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {text!r}")


def number(value, path, field):
    """A record's numeric ID, or a clean error naming the file and field."""
    try:
        return int(value)
    except (TypeError, ValueError):
        fail(f"{path}: {field} {str(value)[:40]!r} isn't a number.")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # asset names can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--assets", action="append", required=True, help="saved search_discovery_assets result (repeat per page)")
    ap.add_argument("--rules", action="append", default=[], help="saved media rule list result (repeat per scope and page)")
    ap.add_argument("--details", action="append", default=[], help="saved get_discovery_media_rule result(s)")
    ap.add_argument("--multi-slot", dest="multi", help="saved get_discovery_multi_slot_customizations result")
    ap.add_argument("--today", type=day, help="YYYY-MM-DD to measure age against (default: today in UTC)")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    today = a.today or datetime.now(timezone.utc).date()
    now = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)

    assets, files = {}, {}
    for p in a.assets:
        for r in records(p):
            if r.get("sharedDataId") is not None and not r.get("deleted"):
                aid = number(r["sharedDataId"], p, "sharedDataId")
                assets[aid], files[aid] = r, p
    rules = {}
    for p in a.rules:
        for r in records(p):
            if r.get("id") is not None:
                rules[number(r["id"], p, "id")] = r
    details = {}
    for p in a.details:
        for d in records(p):
            if d.get("id") is not None:
                details[number(d["id"], p, "id")] = d
    multi_ids = ({number(r["id"], a.multi, "id") for r in records(a.multi) if r.get("id") is not None}
                 if a.multi else set())

    def is_live(rule_id):
        r = {**rules.get(rule_id, {}), **details.get(rule_id, {})}
        tag = r.get("durationTag")
        return r.get("enabled") is not False and tag != "expired" and not r.get("deleted")

    # Which rules use which asset
    used_by, rule_out = {}, []
    for rid in sorted(set(rules) | set(details)):
        meta = {**rules.get(rid, {}), **details.get(rid, {})}
        live = is_live(rid)
        found = []

        def add(sev, check, issue, evidence=None, found=found):
            f = {"severity": sev, "check": check, "issue": issue}
            if evidence:
                f["evidence"] = redact(evidence)[:200]
            found.append(f)

        if rid in details:
            for aid in referenced_ids(details[rid]):
                used_by.setdefault(aid, []).append({"rule_id": rid, "name": meta.get("name"), "live": live})
                if aid not in assets:
                    add("high" if live else "medium", "missing_asset",
                        f"Uses asset {aid}, which isn't in the asset library (deleted, or on another site)")
            placement_checks(details[rid], add)
            if (meta.get("variantCount") or 1) > 1:
                add("low", "variants_not_checked", f"Has {meta.get('variantCount')} A/B variants; only the returned "
                    "variant's assets were checked")
        if found:
            for f in found:
                if f["severity"] == "high" and not live:
                    f["severity"] = "medium"
            rule_out.append({"rule_id": rid, "name": meta.get("name"), "live": live, "scope": meta.get("queries"),
                             "findings": sorted(found, key=lambda f: ORDER[f["severity"]])})
    missing_details = sorted(set(rules) - set(details))
    missing_multi = sorted(multi_ids - set(details))

    # Per-asset verdicts
    stale_cut = now.timestamp() - RULES["stale_days"] * 86400
    image_owner = {}
    asset_out, loads, app_urls = [], {}, []
    for aid, asset in sorted(assets.items()):
        found, urls = asset_checks(asset, app_urls)
        refs = used_by.get(aid, [])
        live_refs = [r for r in refs if r["live"]]
        if live_refs:
            usage = "live"
        elif refs:
            usage = "inactive_only"
            found.append({"severity": "low", "check": "inactive_only",
                          "issue": f"Used only by {len(refs)} disabled or expired rule(s)"})
        else:
            usage = "unused" if not missing_details else "unused_unverified"
            found.append({"severity": "low", "check": "unused", "issue": "No media rule uses it" + (
                "" if not missing_details else f" (unverified: {len(missing_details)} rule(s) weren't fetched in detail)")})
        field = "modifiedAt" if asset.get("modifiedAt") not in (None, "") else "createdAt"
        try:
            modified = when(asset.get(field))
        except (ValueError, OverflowError, OSError):
            fail(f"{files[aid]}: asset {aid} has a {field} that isn't a date ({str(asset.get(field))[:40]!r}).")
        if modified and modified.timestamp() < stale_cut and usage != "live":
            found.append({"severity": "low", "check": "stale",
                          "issue": f"Not changed since {modified:%Y-%m-%d}, more than {RULES['stale_days']} days ago"})
        shared = parse_shared(asset.get("sharedData")) or {}
        if usage == "live" and (shared.get("banner") or {}).get("enabled") is False:
            found.append({"severity": "medium", "check": "disabled_but_used",
                          "issue": "The asset is switched off but a live rule uses it"})
        for kind, u, method in urls:
            if kind == "image":
                image_owner.setdefault(u, []).append(aid)
            e = loads.setdefault(u, {"url": u, "shown": redact(u), "kind": kind, "head_only": method == "head",
                                     "live": False, "assets": []})
            e["live"] = e["live"] or usage == "live"
            e["assets"].append(aid)
        # A broken link in a live asset matters most; on an unused asset it's housekeeping.
        if usage != "live":
            for f in found:
                if f["severity"] == "high":
                    f["severity"] = "medium"
        found.sort(key=lambda f: ORDER[f["severity"]])
        worst = found[0]["severity"] if found else None
        asset_out.append({"asset_id": aid, "name": asset.get("name"), "type": asset.get("dataType"),
                          "banner_type": (shared.get("banner") or {}).get("bannerType"),
                          "modified": f"{modified:%Y-%m-%d}" if modified else None, "usage": usage,
                          "used_by": refs, "priority": worst, "findings": found})
    for u, ids in image_owner.items():
        if len(ids) > 1:
            for a_ in asset_out:
                if a_["asset_id"] in ids:
                    a_["findings"].append({"severity": "low", "check": "duplicate_image",
                                           "issue": f"Same image as asset(s) {', '.join(str(i) for i in ids if i != a_['asset_id'])}"})
    asset_out.sort(key=lambda r: (ORDER.get(r["priority"], 9), r["usage"] != "live", r["asset_id"]))
    ordered = sorted(loads.values(), key=lambda e: (not e["live"], e["url"]))
    cap = RULES["max_links_to_load"]
    count = lambda sev: sum(1 for x in asset_out for f in x["findings"] if f["severity"] == sev) + \
        sum(1 for x in rule_out for f in x["findings"] if f["severity"] == sev)
    usage_counts = {}
    for x in asset_out:
        usage_counts[x["usage"]] = usage_counts.get(x["usage"], 0) + 1
    out = {"ok": True, "today": f"{today:%Y-%m-%d}",
           "summary": {"assets": len(asset_out), "by_usage": usage_counts, "rules": len(rules) or len(details),
                       "rules_with_findings": len(rule_out),
                       "findings": {s: count(s) for s in ("high", "medium", "low")}},
           "assets": asset_out, "rules": rule_out,
           "links_to_load": ordered[:cap], "links_over_cap": ordered[cap:],
           "not_checked": {"rules_without_detail": missing_details, "multi_slot_rules_without_detail": missing_multi,
                           "bloomreach_app_urls": sorted(set(app_urls))}}
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
