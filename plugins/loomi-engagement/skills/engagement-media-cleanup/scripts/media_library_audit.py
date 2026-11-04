#!/usr/bin/env python3
"""Audit a Bloomreach Engagement project's media library and reusable content against what uses it.

Usage:
  python3 media_library_audit.py --files root.json [--files folder_2.json ...]
         [--asset email_block=blocks.json --asset snippet=snippet_<id>.json ...]
         [--usage email=email_<id>.json --usage scenario=scenario_<id>.json --usage banner=banner_<id>.json ...]
         [--denied in_app_message ...] [--today 2026-11-04] [--out audit.json]

--files   saved get_directory results (one per folder) or search_files results: the file library.
--asset   KIND=FILE, a saved list or detail of reusable content. KIND is email_block, snippet, email_asset,
          sms_asset or app_inbox_design. Details (with content) are what let files inside blocks and snippets be found.
--usage   KIND=FILE, a saved detail (or a list of full records) of content that can use files and assets. KIND is
          email (search_email_campaigns with include_design=True), scenario (search_scenarios with
          include_node_designs=True), sms (search_sms_campaigns), banner (search_banners by ID) or in_app_message
          (search_in_app_messages by ID).
--denied  a usage or asset kind whose tool returned HTTP 403, or that wasn't loaded on purpose.

Matches files by their ID (it's part of every file URL) and blocks and snippets by the ID in {{ block('<id>') }} and
{{ snippet('<id>') }}, through blocks and snippets to the campaigns that use them. Prints JSON: each file and asset with
where it's used (live, draft only, template only, unused, unused unverified, not traceable), its findings (oversized,
archived but in use, duplicate, test-looking name, stale, http) and a suggested action (fix, review, delete candidate,
keep); content findings (images without alt text, images on http://) per campaign, scenario, weblayer or block; the
delete and review lists; and what couldn't be checked. Rules are in references/rules.json. Never prints editor names,
message content or URL query strings. Standard library only; no network.
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

RULES_PATH = Path(__file__).resolve().parent.parent / "references" / "rules.json"
ORDER = {"high": 0, "medium": 1, "low": 2}
USAGE_KINDS = ("email", "scenario", "sms", "banner", "in_app_message")
ASSET_KINDS = ("email_block", "snippet", "email_asset", "sms_asset", "app_inbox_design")
LEVELS = {"live": 4, "draft": 3, "template": 2, "archived": 1, "none": 0}
SKIP_KEYS = {"created_by_display_name", "edited_by_display_name", "created_by_id", "edited_by_id", "company_id",
             "initiative_id", "scenario_id", "version_id"}
ID_TOKEN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|(?<![0-9a-f])[0-9a-f]{24}(?![0-9a-f])",
                      re.I)
CONTEXT_ERROR = re.compile(r"\bproject\b|organi[sz]ation|\baccount\b|workspace|permission|\baccess\b|denied|"
                           r"forbidden|unauthori[sz]ed|\b40[13]\b|\b429\b|rate.?limit|too many", re.I)
NOT_FOUND = re.compile(r"not.?found|does not exist|doesn't exist|no such", re.I)
URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.I)
CSS_URL = re.compile(r"url\(\s*['\"]?\s*(http://[^'\")\s]+)", re.I)
CONTENT_KEYS = {"jinja_html", "design", "html", "text", "translations", "content", "variants", "beefree_template",
                "nodes", "split", "action", "params", "snippet"}


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


def redact(text):
    return URL.sub("[url]", str(text or "no error text"))[:200]


def load_rules():
    try:
        return json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        fail(f"can't read references/rules.json ({e}).")


def load(path):
    """A saved tool result. Returns (records, extra) with the result/data wrappers removed, or (None, reason) for a
    not-found on the item itself. Other tool errors stop the run."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        fail(f"{path}: can't read it as JSON ({e}).")
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            err = redact(d.get("error"))
            if CONTEXT_ERROR.search(err):
                fail(f"{path}: Loomi Connect returned an error about the project, organisation or access ({err}). "
                     "Check the project; pass the kind with --denied if the tool is denied. Don't treat it as "
                     "'nothing uses it'.")
            if NOT_FOUND.search(err):
                return None, err
            fail(f"{path}: the tool returned an error ({err}). This check couldn't run.")
    if isinstance(data, dict) and isinstance(data.get("result"), (dict, list)):
        data = data["result"]
    if isinstance(data, list):
        out = []
        for item in data:
            if isinstance(item, dict) and "success" in item and "data" in item:
                if item.get("success") is False:
                    fail(f"{path}: one of the saved results is a tool error ({redact(item.get('error'))}).")
                item = item["data"]
            if isinstance(item, dict):
                out.append(item)
        return out, {}
    if not isinstance(data, dict):
        return [], {}
    inner = data.get("data", data)
    if isinstance(inner, dict):
        return [inner], data
    return [r for r in (inner or []) if isinstance(r, dict)], data


def pairs(values, what, kinds):
    out = []
    for v in values or []:
        if "=" not in v:
            fail(f"{what} needs KIND=FILE, got {v!r}.")
        kind, path = v.split("=", 1)
        kind = kind.strip()
        if kind not in kinds:
            fail(f"{what}: unknown kind {kind!r}; use one of {', '.join(kinds)}.")
        out.append((kind, path.strip()))
    return out


def when(v):
    if v in (None, "") or isinstance(v, bool):
        return None
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc).date()
        return datetime.fromisoformat(str(v).strip().replace("Z", "+00:00")).date()
    except (ValueError, OverflowError, OSError):
        return None


def whole(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v == v and abs(v) != float("inf"):
        return int(v)
    if isinstance(v, str) and re.fullmatch(r"\s*\d+\s*", v):
        return int(v)
    return None


def dims(v):
    """(width, height) from '600x400' or {'width': .., 'height': ..}, or None."""
    if isinstance(v, dict):
        w, h = whole(v.get("width")), whole(v.get("height"))
        return (w, h) if w and h else None
    m = re.fullmatch(r"\s*(\d+)\s*[x×]\s*(\d+)\s*", str(v or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def size_shown(n):
    if n is None:
        return None
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    return f"{max(1, round(n / 1000))} KB"


def shown_url(u):
    """A URL safe to show: scheme, host and path only (no user info, query or fragment), cut short."""
    try:
        p = urlsplit(u.strip())
    except ValueError:
        return "[unreadable URL]"
    host = (p.hostname or "")
    path = p.path if len(p.path) <= 60 else p.path[:57] + "..."
    return f"{p.scheme}://{host}{path}"


def words(text):
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def norm_name(name, patterns):
    s = str(name or "").strip().lower()
    for pat in patterns:
        s = re.sub(pat, "", s, flags=re.I)
    return re.sub(r"[\s_\-.]+", " ", s).strip()


def walk_strings(obj, top=True):
    """Every string value in a record, leaving out editor and bookkeeping fields (and the record's own _id)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in SKIP_KEYS or (top and k == "_id"):
                continue
            yield from walk_strings(v, False)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_strings(v, False)
    elif isinstance(obj, str):
        yield obj


class Images(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.imgs = []
        self.backgrounds = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "img":
            self.imgs.append(a)
        if a.get("background"):
            self.backgrounds.append(a["background"])


def is_pixel(attrs, max_px):
    w, h = whole(re.sub(r"px$", "", str(attrs.get("width", "")).strip())), \
        whole(re.sub(r"px$", "", str(attrs.get("height", "")).strip()))
    return w is not None and h is not None and w <= max_px and h <= max_px


def scan_content(record, rules):
    """Images in a record's HTML and Visual Builder JSON: [(src, alt_ok)] and the http:// image URLs."""
    images, insecure = {}, set()

    def from_html(text):
        p = Images()
        try:
            p.feed(text)
            p.close()
        except Exception:  # malformed markup: keep what was parsed
            pass
        for a in p.imgs:
            src = a.get("src", "").strip()
            if not src or is_pixel(a, rules["tracking_pixel_max_px"]):
                continue
            ok = bool(a.get("alt", "").strip())
            images[src] = images.get(src, False) or ok
            if src.lower().startswith("http://"):
                insecure.add(src)
        for b in p.backgrounds:
            if b.strip().lower().startswith("http://"):
                insecure.add(b.strip())

    def from_json(obj):
        if isinstance(obj, dict):
            src = obj.get("src")
            if isinstance(src, str) and src.strip() and "alt" in obj:
                ok = bool(str(obj.get("alt") or "").strip())
                images[src.strip()] = images.get(src.strip(), False) or ok
                if src.strip().lower().startswith("http://"):
                    insecure.add(src.strip())
            for v in obj.values():
                from_json(v)
        elif isinstance(obj, list):
            for v in obj:
                from_json(v)
        elif isinstance(obj, str):
            scan_string(obj)

    def scan_string(s):
        if "<img" in s.lower() or "background=" in s.lower():
            from_html(s)
        for m in CSS_URL.finditer(s):
            insecure.add(m.group(1))
        t = s.lstrip()
        if t[:1] in "{[" and '"src"' in s:
            try:
                from_json(json.loads(s))
            except ValueError:
                pass

    for s in walk_strings(record):
        scan_string(s)
    return images, insecure


def status_level(rec, rules):
    if rec.get("archived") is True:
        return "archived"
    status = str(rec.get("status") or "").strip().lower()
    if not status and isinstance(rec.get("enabled"), bool):
        status = "enabled" if rec["enabled"] else "inactive"
    return "live" if status in {s.lower() for s in rules["live_statuses"]} else "draft"


def has_content(rec):
    return any(k in rec and rec[k] not in (None, "", [], {}) for k in CONTENT_KEYS)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rules = load_rules()
    ap = argparse.ArgumentParser(description="Audit Engagement media files and reusable content against their usage.")
    ap.add_argument("--files", action="append", default=[],
                    help="a saved get_directory or search_files result (repeat for every folder)")
    ap.add_argument("--asset", action="append", default=[],
                    help="KIND=FILE: saved reusable content (email_block, snippet, email_asset, sms_asset, "
                         "app_inbox_design), list or detail")
    ap.add_argument("--usage", action="append", default=[],
                    help="KIND=FILE: saved content that can use files and assets (email, scenario, sms, banner, "
                         "in_app_message), with designs")
    ap.add_argument("--denied", action="append", default=[],
                    help="a kind whose tool returned 403 or that wasn't loaded; its absence makes 'unused' unverified")
    ap.add_argument("--stale-days", type=int, default=rules["stale_days"],
                    help="unused items older than this go on the delete list (default from rules.json)")
    ap.add_argument("--today", help="today's date as YYYY-MM-DD (default: today in UTC)")
    ap.add_argument("--out", help="also write the JSON to this file in your working folder")
    args = ap.parse_args()
    if args.today:
        try:
            today = date.fromisoformat(args.today)
        except ValueError:
            fail(f"--today must be YYYY-MM-DD, got {args.today!r}.")
    else:
        today = datetime.now(timezone.utc).date()
    for k in args.denied:
        if k not in USAGE_KINDS + ASSET_KINDS:
            fail(f"--denied: unknown kind {k!r}.")
    if not args.files and not args.asset:
        fail("give at least one --files or --asset input: there's nothing to audit.")

    # 1. The file library.
    files, folders, browsed = {}, set(), set()
    for path in args.files:
        recs, extra = load(path)
        if recs is None:
            continue
        extra = extra if isinstance(extra, dict) else {}
        for d in extra.get("directories") or []:
            if isinstance(d, dict) and d.get("_id"):
                folders.add(str(d["_id"]))
        crumbs = [c for c in extra.get("path") or [] if isinstance(c, dict) and c.get("_id")]
        if crumbs:
            browsed.add(str(crumbs[-1]["_id"]))
        for r in recs:
            if r.get("_id") and (r.get("variants") is not None or r.get("file_type") or r.get("mime_type")):
                files[str(r["_id"])] = {**files.get(str(r["_id"]), {}), **r}
                if r.get("parent_id"):
                    browsed.add(str(r["parent_id"]))

    # 2. Reusable content (lists and details merged by ID; details carry content).
    assets = {}
    for kind, path in pairs(args.asset, "--asset", ASSET_KINDS):
        recs, _ = load(path)
        for r in recs or []:
            if r.get("_id"):
                key = str(r["_id"])
                prev = assets.get(key, {"kind": kind, "rec": {}})
                assets[key] = {"kind": kind, "rec": {**prev["rec"], **r}}

    # 3. Content that uses files and assets.
    usage = {}
    for kind, path in pairs(args.usage, "--usage", USAGE_KINDS):
        recs, _ = load(path)
        for r in recs or []:
            if r.get("_id"):
                key = (kind, str(r["_id"]))
                usage[key] = {**usage.get(key, {}), **r}

    targets = set(files) | set(assets)
    # Containers: usage records and asset records with content.
    containers = []
    for (kind, uid), rec in sorted(usage.items()):
        containers.append({"kind": kind, "id": uid, "name": str(rec.get("name") or uid), "rec": rec,
                           "base": status_level(rec, rules), "asset": False})
    for aid, a in sorted(assets.items()):
        if has_content(a["rec"]):
            containers.append({"kind": a["kind"], "id": aid, "name": str(a["rec"].get("name") or aid),
                               "rec": a["rec"], "base": None, "asset": True})

    refs = {}  # target id -> list of container indexes
    for i, c in enumerate(containers):
        found = set()
        for s in walk_strings(c["rec"]):
            for m in ID_TOKEN.finditer(s):
                tok = m.group(0).lower()
                if tok in targets and tok != c["id"]:
                    found.add(tok)
        for t in found:
            refs.setdefault(t, []).append(i)

    # SMS templates are copied, not referenced: match their text in SMS campaigns and scenarios.
    copy_users = {}
    sms_texts = {}
    for aid, a in assets.items():
        if a["kind"] != "sms_asset":
            continue
        rec = a["rec"]
        text = rec.get("text")
        if not text and isinstance(rec.get("design"), dict):
            tr = rec["design"].get("translations") or {}
            first = tr.get("") or next(iter(tr.values()), {}) if isinstance(tr, dict) else {}
            text = first.get("message") if isinstance(first, dict) else None
        t = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(t) >= rules["min_copy_text_chars"]:
            sms_texts[aid] = t
    if sms_texts:
        for i, c in enumerate(containers):
            if c["asset"] or c["kind"] not in ("sms", "scenario"):
                continue
            blob = " ".join(re.sub(r"\s+", " ", s) for s in walk_strings(c["rec"]))
            for aid, t in sms_texts.items():
                if t in blob:
                    copy_users.setdefault(aid, []).append(i)

    # 4. Levels, propagated through blocks and snippets until nothing changes.
    template_kinds = set(rules["template_kinds"])
    level = {t: 0 for t in targets}

    def clevel(c):
        if not c["asset"]:
            return LEVELS[c["base"]]
        own = level.get(c["id"], 0)
        return max(own, LEVELS["template"]) if c["kind"] in template_kinds else own

    for _ in range(len(targets) + 2):
        changed = False
        for t in targets:
            users = refs.get(t, []) + copy_users.get(t, [])
            new = max([clevel(containers[i]) for i in users] or [0])
            if new > level[t]:
                level[t], changed = new, True
        if not changed:
            break

    # 5. Coverage.
    loaded_usage = {k for k, _ in usage}
    missing = sorted(k for k in rules["required_usage_kinds"] if k not in loaded_usage or k in args.denied)
    no_content = sorted(aid for aid, a in assets.items()
                        if a["kind"] in rules["content_asset_kinds"] and not has_content(a["rec"]))
    unloaded_content_kinds = sorted(k for k in rules["content_asset_kinds"]
                                    if k in args.denied or not any(a["kind"] == k for a in assets.values()))

    def unverified_reasons(for_file):
        reasons = [f"{k} not checked" for k in missing]
        if for_file:
            if no_content:
                reasons.append(f"{len(no_content)} blocks or snippets loaded without content")
            reasons += [f"{k} not loaded" for k in unloaded_content_kinds]
        return reasons

    level_name = {v: k for k, v in LEVELS.items()}
    test_words = {w.lower() for w in rules["test_name_words"]}
    stale_cut = args.stale_days

    def users_of(t):
        idx = sorted(set(refs.get(t, []) + copy_users.get(t, [])),
                     key=lambda i: (-clevel(containers[i]), containers[i]["kind"], containers[i]["name"].lower()))
        out = [{"kind": containers[i]["kind"], "name": containers[i]["name"], "id": containers[i]["id"],
                "level": level_name[clevel(containers[i])],
                **({"how": "copied text"} if i in copy_users.get(t, []) else {})} for i in idx]
        return out[:rules["max_users_listed"]], len(out)

    def state_of(t, kind_is_template, for_file):
        lv = level[t]
        if lv == LEVELS["live"]:
            return "live"
        if lv == LEVELS["draft"]:
            return "draft_only"
        if lv == LEVELS["template"]:
            return "template_only"
        if kind_is_template:
            return "not_traceable"
        return "unused_unverified" if unverified_reasons(for_file) else "unused"

    def add(lst, priority, code, detail):
        lst.append({"priority": priority, "code": code, "detail": detail})

    def age_days(rec):
        d = when(rec.get("edited")) or when(rec.get("created"))
        return (today - d).days if d else None

    # 6. Files.
    file_rows = []
    for fid, rec in files.items():
        f = []
        name = str(rec.get("name") or fid)
        variants = rec.get("variants") if isinstance(rec.get("variants"), dict) else {}
        orig = variants.get("original") if isinstance(variants.get("original"), dict) else {}
        size = whole(orig.get("file_size"))
        dim = dims(orig.get("dimensions"))
        ftype = str(rec.get("file_type") or "").lower()
        is_image = ftype == "image" or str(rec.get("mime_type") or "").lower().startswith("image/")
        state = state_of(fid, False, True)
        live = state == "live"
        archived = rec.get("archived") is True or rec.get("implicitly_archived") is True
        if archived and state in ("live", "draft_only"):
            add(f, "high" if live else "medium", "archived_in_use",
                "Archived, but " + ("live" if live else "draft") + " content still uses it.")
        if is_image and size is not None:
            if size > rules["huge_image_bytes"]:
                add(f, "high" if live else "medium", "huge_image", f"{size_shown(size)}: far too heavy for email "
                    "or web; compress or resize it.")
            elif size > rules["large_image_bytes"]:
                add(f, "medium" if live else "low", "large_image", f"{size_shown(size)}: slows loading on mobile; "
                    "compress it.")
        if is_image and dim and max(dim) > rules["max_image_width_px"]:
            add(f, "low", "oversized_dimensions", f"{dim[0]}x{dim[1]} pixels: resize to the size it's shown at.")
        for vname, v in sorted(variants.items()):
            if isinstance(v, dict) and str(v.get("url") or "").lower().startswith("http://"):
                add(f, "medium", "insecure_url", f"The {vname} file is served over http://.")
                break
        if words(name) & test_words or re.search(r"\bcopy of\b", name, re.I):
            add(f, "low", "test_name", "The name looks like a test, placeholder or throwaway copy.")
        age = age_days(rec)
        if state in ("unused", "unused_unverified") and age is not None and age > stale_cut:
            add(f, "low", "stale", f"Unused, uploaded {age} days ago.")
        users, n_users = users_of(fid)
        created = when(rec.get("created"))
        file_rows.append({"id": fid, "name": name, "file_type": ftype or None, "size_bytes": size,
                          "size": size_shown(size), "dimensions": f"{dim[0]}x{dim[1]}" if dim else None,
                          "created": created.isoformat() if created else None,
                          "archived": archived, "state": state, "used_by": users, "used_by_count": n_users,
                          "findings": f, "_norm": norm_name(name, rules["name_noise_patterns"]), "_age": age})

    # Duplicates: same normalised name and size, or (above a minimum size) same size and dimensions.
    def keeper_key(r):
        return (-LEVELS.get({"live": "live", "draft_only": "draft", "template_only": "template"}.get(r["state"], "none"),
                            0), r["created"] or "9999", r["id"])

    groups = {}
    for r in file_rows:
        if r["size_bytes"] is None:
            continue
        groups.setdefault(("name", r["_norm"], r["size_bytes"]), []).append(r)
        if r["size_bytes"] >= rules["min_duplicate_bytes"] and r["dimensions"]:
            groups.setdefault(("size", r["size_bytes"], r["dimensions"]), []).append(r)
    marked = set()
    for key in sorted(groups, key=lambda k: (k[0] != "name", str(k[1:]))):
        g = groups[key]
        if len(g) < 2:
            continue
        g = sorted(g, key=keeper_key)
        keep = g[0]
        for r in g[1:]:
            if r["id"] in marked:
                continue
            marked.add(r["id"])
            how = "same name and size" if key[0] == "name" else "same size and dimensions, different name"
            add(r["findings"], "low", "duplicate", f"Duplicate of '{keep['name']}' ({keep['id']}): {how}.")

    # 7. Assets.
    asset_rows = []
    name_groups = {}
    for aid, a in assets.items():
        rec, kind = a["rec"], a["kind"]
        f = []
        name = str(rec.get("name") or aid)
        state = state_of(aid, kind in template_kinds, False)
        if rec.get("archived") is True and state in ("live", "draft_only"):
            add(f, "high" if state == "live" else "medium", "archived_in_use",
                "Archived, but " + ("live" if state == "live" else "draft") + " content still uses it.")
        if words(name) & test_words or re.search(r"\bcopy of\b", name, re.I):
            add(f, "low", "test_name", "The name looks like a test, placeholder or throwaway copy.")
        age = age_days(rec)
        if state in ("unused", "unused_unverified", "not_traceable") and age is not None and age > stale_cut:
            add(f, "low", "stale", f"Not used anywhere checked, last edited {age} days ago.")
        users, n_users = users_of(aid)
        row = {"kind": kind, "id": aid, "name": name, "archived": rec.get("archived") is True, "state": state,
               "content_loaded": has_content(rec), "used_by": users, "used_by_count": n_users, "findings": f,
               "_age": age}
        asset_rows.append(row)
        name_groups.setdefault((kind, norm_name(name, rules["name_noise_patterns"])), []).append(row)
    for key in sorted(name_groups):
        g = name_groups[key]
        if len(g) < 2 or not key[1]:
            continue
        g = sorted(g, key=lambda r: (-{"live": 3, "draft_only": 2, "template_only": 1}.get(r["state"], 0), r["id"]))
        for r in g[1:]:
            add(r["findings"], "low", "duplicate_name", f"Same name as '{g[0]['name']}' ({g[0]['id']}).")

    # 8. Content findings: images without alt text and images on http://.
    content_rows = []
    alt_kinds = set(rules["alt_text_kinds"])
    file_by_token = files
    for c in containers:
        images, insecure = scan_content(c["rec"], rules)
        lv = level_name[clevel(c)] if c["asset"] else c["base"]
        if lv == "archived":
            continue
        live = lv == "live"
        row = {"kind": c["kind"], "id": c["id"], "name": c["name"], "level": lv, "findings": []}
        if c["kind"] in alt_kinds:
            missing_alt = sorted(src for src, ok in images.items() if not ok)
            if missing_alt:
                lib = sorted({file_by_token[m.group(0).lower()].get("name") or m.group(0).lower()
                              for src in missing_alt for m in ID_TOKEN.finditer(src)
                              if m.group(0).lower() in file_by_token})
                add(row["findings"], "medium" if live else "low", "missing_alt",
                    f"{len(missing_alt)} of {len(images)} images have no alt text"
                    + (f" (library files: {', '.join(lib[:5])}{'...' if len(lib) > 5 else ''})" if lib else "")
                    + ". Add alt text, or alt=\"\" only for purely decorative images.")
                for m_src in missing_alt:
                    for m in ID_TOKEN.finditer(m_src):
                        tok = m.group(0).lower()
                        fr = next((r for r in file_rows if r["id"] == tok), None)
                        if fr is not None and not any(x["code"] == "missing_alt" for x in fr["findings"]):
                            add(fr["findings"], "medium" if live else "low", "missing_alt",
                                f"Used without alt text in {c['kind']} '{c['name']}'.")
        if insecure:
            hosts = sorted({shown_url(u) for u in insecure})
            add(row["findings"], "high" if live else "medium", "insecure_image",
                f"{len(insecure)} image URL{'s' if len(insecure) != 1 else ''} on http:// (browsers block them on https pages and some email clients "
                f"warn): {', '.join(hosts[:3])}{'...' if len(hosts) > 3 else ''}.")
        if row["findings"]:
            row["findings"].sort(key=lambda x: (ORDER[x["priority"]], x["code"]))
            content_rows.append(row)

    # 9. Actions.
    def action(r):
        pri = [x["priority"] for x in r["findings"]]
        fixable = {"archived_in_use", "huge_image", "large_image", "insecure_url", "missing_alt", "oversized_dimensions"}
        if r["state"] in ("live", "draft_only") and any(x["code"] in fixable and x["priority"] in ("high", "medium")
                                                        for x in r["findings"]):
            return "fix"
        if r["state"] == "unused":
            if (r["_age"] is not None and r["_age"] > stale_cut) or any(
                    x["code"] in ("test_name", "duplicate", "duplicate_name") for x in r["findings"]):
                return "delete_candidate"
            return "review"
        if r["state"] in ("unused_unverified", "not_traceable", "template_only"):
            return "review"
        if any(x["code"] in ("duplicate", "duplicate_name", "test_name") for x in r["findings"]):
            return "review"
        return "keep" if not pri or all(p == "low" for p in pri) else "review"

    for r in file_rows + asset_rows:
        r["findings"].sort(key=lambda x: (ORDER[x["priority"]], x["code"]))
        r["action"] = action(r)
        r["priority"] = r["findings"][0]["priority"] if r["findings"] else None

    def sort_key(r):
        return (ORDER.get(r["priority"], 3), r.get("kind", "file"), r["name"].lower(), r["id"])

    file_rows.sort(key=sort_key)
    asset_rows.sort(key=sort_key)
    content_rows.sort(key=lambda r: (ORDER[r["findings"][0]["priority"]], r["kind"], r["name"].lower(), r["id"]))

    def brief(r, what):
        return {"what": what, "id": r["id"], "name": r["name"], "state": r["state"],
                "why": "; ".join(x["detail"] for x in r["findings"]) or r["state"].replace("_", " ")}

    delete_list = [brief(r, "file") for r in file_rows if r["action"] == "delete_candidate"] + \
                  [brief(r, r["kind"]) for r in asset_rows if r["action"] == "delete_candidate"]
    review_list = [brief(r, "file") for r in file_rows if r["action"] == "review"] + \
                  [brief(r, r["kind"]) for r in asset_rows if r["action"] == "review"]
    fix_list = [brief(r, "file") for r in file_rows if r["action"] == "fix"] + \
               [brief(r, r["kind"]) for r in asset_rows if r["action"] == "fix"]

    not_checked = [f"{k}: not loaded or denied, so 'unused' is unverified" for k in missing]
    if no_content:
        not_checked.append(f"{len(no_content)} blocks or snippets were loaded from the list only (no content), so "
                           "files used inside them weren't found.")
    not_checked += [f"{k}: not loaded, so files used inside them weren't found" for k in unloaded_content_kinds]
    if any(a["kind"] in template_kinds for a in assets.values()):
        not_checked.append("Email, SMS and app inbox templates are copied into campaigns when used, so where they "
                           "were used can't be traced (SMS templates are matched by identical text only).")
    if not files:
        not_checked.append("File library: no files were loaded.")
    unbrowsed = sorted(folders - browsed)
    if unbrowsed:
        not_checked.append(f"{len(unbrowsed)} folders listed in the inputs had no files loaded from them (empty, or "
                           "not browsed with get_directory): " + ", ".join(unbrowsed[:10])
                           + ("..." if len(unbrowsed) > 10 else "") + ".")

    def counts(rows, key):
        out = {}
        for r in rows:
            out[r[key]] = out.get(r[key], 0) + 1
        return dict(sorted(out.items()))

    strip = lambda rows: [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]  # noqa: E731
    result = {
        "ok": True,
        "today": today.isoformat(),
        "summary": {
            "files": len(file_rows),
            "files_by_state": counts(file_rows, "state"),
            "assets": len(asset_rows),
            "assets_by_kind": counts(asset_rows, "kind"),
            "assets_by_state": counts(asset_rows, "state"),
            "content_checked": len(containers),
            "content_with_findings": len(content_rows),
            "to_fix": len(fix_list),
            "delete_candidates": len(delete_list),
            "to_review": len(review_list),
        },
        "fix": fix_list,
        "delete_candidates": delete_list,
        "review": review_list,
        "content_findings": content_rows,
        "files": strip(file_rows),
        "assets": strip(asset_rows),
        "not_checked": not_checked,
    }
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text + "\n")
        except OSError as e:
            fail(f"can't write {args.out} ({e}).")
    print(text)


if __name__ == "__main__":
    main()
