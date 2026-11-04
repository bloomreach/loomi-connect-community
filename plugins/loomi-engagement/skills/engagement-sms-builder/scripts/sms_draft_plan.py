#!/usr/bin/env python3
"""Plan one Bloomreach Engagement SMS campaign draft (a create, or an update of a draft), and check the read-back.

Usage:
  python3 sms_draft_plan.py senders --campaigns detail.json [--campaigns detail.json ...] [--out senders.json]
  python3 sms_draft_plan.py plan --draft draft.json --project-id ID --project-name NAME --consent consent.json
         [--campaigns detail.json ...] [--segmentations detail.json ...] [--customer-filters detail.json ...]
         [--existing detail.json] [--created-id ID] [--today YYYY-MM-DD] --out plan.json
  python3 sms_draft_plan.py verify --plan plan.json --readback 1=readback.json [--out result.json]

senders: lists the senders (display name and sender ID) used by existing SMS campaigns (saved search_sms_campaigns
details), newest first. The default is the newest one whose name doesn't look like a placeholder.

plan: --draft is the draft spec (references/draft-format.md), holding the message itself. --consent is a saved
get_consent_settings result, --campaigns saved search_sms_campaigns details (to check the sender), --segmentations
and --customer-filters saved detail results for the audience. --existing is the saved search_sms_campaigns detail of
the draft being revised: with it the plan is an update_sms_campaign of that draft (the fetched object with only the
changed keys replaced, because the tool replaces the whole campaign), and without it a create_sms_campaign. It lints
every message (GSM-7 or UCS-2 and segments, STOP, brand, HELP, links, Jinja, placeholders), the consent, sender and
audience, and the schedule against quiet hours, and prints a plan in the shape in docs/skill-authoring.md ("Plan
files for write skills") with project_id and project_name in place of account and environment. The full plan goes to
--out (required); stdout gets the same without payload, undo and expect. Editor names, server timestamps and
schedule.active are stripped from an update's payload and undo. --created-id is the id create_sms_campaign returned in
this session: a revision with origin created_this_session must name that campaign.

verify: --readback 1=FILE is the search_sms_campaigns campaign_id detail after the write. Reports the change as
in_place or not_in_place. An error about the project, organisation, account or access stops it.

It never calls Loomi Connect: the assistant makes the one write, after confirmation. Standard library only.
"""
import argparse
import datetime as dt
import json
import math
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
NOT_FOUND = re.compile(r"not.?found|does not exist|doesn't exist|no such", re.I)
CONTEXT_ERROR = re.compile(r"\bproject\b|organi[sz]ation|\baccount\b|workspace|permission|\baccess\b|denied|"
                           r"forbidden|unauthori[sz]ed|\b40[13]\b|\b429\b|rate.?limit|too many", re.I)
URL_IN_TEXT = re.compile(r"\S*://\S+|www\.\S+", re.I)  # any scheme, so {{ x }}://host is caught too
PAIRS = {"{{": "}}", "{%": "%}", "{#": "#}"}
OPENER = re.compile(r"\{\{|\{%|\{#")
EXPR_OPENER = re.compile(r"\{\{|\{%")
JINJA_ANY = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.S)
CUSTOMER_REF = re.compile(r"\bcustomer(?:_ids)?\s*(?:\.|\[)")
BLOCK_TAGS = {"for": "endfor", "if": "endif", "macro": "endmacro", "call": "endcall", "filter": "endfilter",
              "raw": "endraw", "with": "endwith", "block": "endblock"}
MIDDLE_TAGS = {"else": ("if", "for"), "elif": ("if",)}
GSM7 = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§"
           "¿abcdefghijklmnopqrstuvwxyzäöñüà")
GSM7_EXT = set("^{}\\[~]|€\f")
SMART = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "..."}
SENDER_ID = re.compile(r"^(?=.*[A-Za-z])[A-Za-z0-9]{1,11}$|^\+?\d{3,17}$")
OFFSET = re.compile(r"^([+-])(\d{2}):(\d{2})$")
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


def redact(text):
    """Error text with URLs removed, so a token in a query string is never printed."""
    return re.sub(r"https?://\S+", "<url>", str(text))


def read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError) as e:
        fail(f"{path}: can't read it ({e}).")


def raw_json(path):
    try:
        return json.loads(read_text(path))
    except ValueError as e:
        fail(f"{path}: can't read it as JSON ({e}).")


def context_stop(path, err):
    fail(f"{path}: Loomi Connect returned an error about the project, account or access ({redact(err)[:160]}). "
         "This step couldn't run; check the project and read it again. Don't treat it as 'nothing found'.")


def unwrap(data):
    if isinstance(data, dict) and isinstance(data.get("result"), (dict, list)):
        data = data["result"]
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], (dict, list)):
        data = data["data"]
    return data


def tool_error(data):
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            return str(d.get("error") or "no error text")
    return None


def load(path):
    """A saved tool result, unwrapped from result and data. A success:false result stops the script."""
    data = raw_json(path)
    err = tool_error(data)
    if err is not None:
        if CONTEXT_ERROR.search(err):
            context_stop(path, err)
        fail(f"{path}: the tool returned an error ({redact(err)[:200]}). This step couldn't run.")
    return unwrap(data)


def host_ok(host, allowed):
    return any(host == h or host.endswith("." + h) for h in allowed)


def records(paths):
    out = []
    for p in paths:
        doc = load(p)
        out += [r for r in (doc if isinstance(doc, list) else [doc]) if isinstance(r, dict)]
    return out


# ---------- senders ----------

def sms_translations(rec):
    """(variant, language, translation) for each SMS translation in a campaign detail."""
    out = []
    for v in ((rec.get("action") or {}).get("variants") or []):
        if isinstance(v, dict):
            for lang, t in sorted((v.get("translations") or {}).items()):
                if isinstance(t, dict):
                    out.append((v, lang, t))
    return out


def looks_placeholder(name):
    low = name.lower()
    return any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low) for w in RULES["name_placeholder_words"])


def list_senders(paths):
    seen = {}
    for r in records(paths):
        if r.get("archived"):
            continue
        keys = set()
        for _v, _lang, t in sms_translations(r):
            s = t.get("sender") or {}
            sid = str(s.get("sender") or "").strip()
            if sid:
                keys.add((str(s.get("name") or "").strip(), sid))
        for key in sorted(keys):
            s = seen.setdefault(key, {"name": key[0], "sender": key[1], "campaigns": 0, "last_edited": 0,
                                      "looks_like_placeholder": looks_placeholder(key[0])})
            s["campaigns"] += 1
            try:
                s["last_edited"] = max(s["last_edited"], float(r.get("edited") or 0))
            except (TypeError, ValueError):
                pass
    return sorted(seen.values(), key=lambda s: (-s["last_edited"], -s["campaigns"], s["sender"].lower(), s["name"]))


def cmd_senders(a):
    senders = list_senders(a.campaigns)
    default = next((s for s in senders if not s["looks_like_placeholder"]), None)
    return {"ok": True, "senders": senders, "default": default,
            "note": "Senders from existing, unarchived SMS campaigns, newest first. The default is the newest whose "
                    "name doesn't look like a placeholder. With none, ask the user for the sender ID registered with "
                    "their SMS provider."}


# ---------- lint ----------

class Lint:
    def __init__(self):
        self.problems, self.warnings = [], []

    def block(self, check, message, where=None):
        self.problems.append({"check": check, "where": where, "message": message})

    def warn(self, check, message, where=None):
        self.warnings.append({"check": check, "where": where, "message": message})


def estimate(text):
    """Text with each {{ }} counted as jinja_estimate_chars characters and {% %} and {# #} dropped."""
    t = re.sub(r"\{%.*?%\}|\{#.*?#\}", "", text, flags=re.S)
    return re.sub(r"\{\{.*?\}\}", "x" * RULES["jinja_estimate_chars"], t, flags=re.S)


def segments(text):
    est = estimate(text)
    gsm = all(c in GSM7 or c in GSM7_EXT for c in est)
    if gsm:
        n = sum(2 if c in GSM7_EXT else 1 for c in est)
        single, part = RULES["gsm7_single_chars"], RULES["gsm7_part_chars"]
    else:
        n = len(est.encode("utf-16-le")) // 2
        single, part = RULES["ucs2_single_chars"], RULES["ucs2_part_chars"]
    segs = 0 if n == 0 else 1 if n <= single else math.ceil(n / part)
    bad = sorted({c for c in est if c not in GSM7 and c not in GSM7_EXT})
    return {"encoding": "GSM-7" if gsm else "UCS-2", "chars": n, "segments": segs,
            "non_gsm_chars": bad, "smart_only": bool(bad) and all(c in SMART for c in bad)}


def jinja_parts(text):
    parts, unclosed, i = [], [], 0
    while True:
        m = OPENER.search(text, i)
        if not m:
            parts.append(("text", text[i:]))
            return parts, unclosed
        parts.append(("text", text[i:m.start()]))
        end = text.find(PAIRS[m.group(0)], m.end())
        nxt = None if m.group(0) == "{#" else EXPR_OPENER.search(text, m.end(), len(text) if end == -1 else end)
        if end == -1 or nxt:
            unclosed.append(text[m.start():m.start() + 40])
            i = nxt.start() if nxt else len(text)
            continue
        parts.append((m.group(0), text[m.end():end]))
        i = end + 2


def check_jinja(lint, where, text):
    parts, unclosed = jinja_parts(text)
    for u in unclosed:
        lint.block("jinja_delimiters", f"Unclosed Jinja delimiter near {u!r}.", where)
    plain = "".join(t for k, t in parts if k == "text")
    for closer in ("}}", "%}", "#}"):
        if closer in plain:
            lint.block("jinja_delimiters", f"Stray {closer!r} with no opening delimiter.", where)
    stack = []
    for kind, inner in parts:
        if kind == "{%":
            word = (re.match(r"\s*-?\s*(\w+)", inner) or [None, ""])[1]
            if word == "set" and "=" not in inner:
                stack.append(("set", "endset"))
            elif word in BLOCK_TAGS:
                stack.append((word, BLOCK_TAGS[word]))
            elif word in MIDDLE_TAGS:
                if not stack or stack[-1][0] not in MIDDLE_TAGS[word]:
                    lint.block("jinja_blocks", f"{{% {word} %}} outside a matching block.", where)
            elif word.startswith("end"):
                if not stack or stack[-1][1] != word:
                    lint.block("jinja_blocks", f"{{% {word} %}} closes a block that isn't open.", where)
                else:
                    stack.pop()
        if kind in ("{{", "{%"):
            expr = re.sub(r"\s*\|\s*", "| ", inner.strip(" -"))
            low = expr.lower()
            if kind == "{{" and not expr.strip():
                continue  # reported by the placeholder check
            for bad in RULES["banned_jinja"]:
                if bad in low:
                    lint.block("jinja_rules", f"'{bad.strip()}' doesn't work in Bloomreach Jinja: {expr[:60]!r}.", where)
            if re.search(r"\brecommendations\(\s*[^'\"\s)]", expr):
                lint.block("jinja_rules", f"A recommendations() engine ID must be a quoted literal: {expr[:60]!r}.", where)
            if re.search(r"\baggregates\[\s*[^'\"\s\]]", expr):
                lint.block("jinja_rules", f"An aggregates[...] key must be a quoted literal: {expr[:60]!r}.", where)
            if re.search(r"\bevent\.", expr):
                lint.block("jinja_rules", "event.* is empty in a campaign that isn't triggered by an event: "
                           f"{expr[:60]!r}.", where)
            if re.search(r"\|\s*(?:e|escape)\b(?!\w)", expr):
                lint.warn("jinja_escape", f"| e in an SMS shows HTML entities such as &amp; to the reader: {expr[:60]!r}.",
                          where)
            for m in re.finditer(r"default\(([^()]*)\)", expr):
                if not re.search(r",\s*true\s*$", m.group(1), re.I):
                    lint.warn("jinja_default", f"| default({m.group(1)}) without true doesn't replace None or '': "
                              "use | default(x, true).", where)
            if kind == "{{" and CUSTOMER_REF.search(expr) and "default(" not in expr:
                lint.block("personalization_fallback", f"{expr[:60]!r} has no fallback, so a customer without it gets "
                           "'None' or a gap in the text. Add | default(x, true).", where)
    for word, _end in reversed(stack):
        lint.block("jinja_blocks", f"{{% {word} %}} is never closed.", where)


def authority_problem(url):
    """Why a link's scheme and host part can't be trusted, or None. Phones and urlsplit can disagree on a host
    written with a backslash or user info (@), and Jinja there decides the host only at send time."""
    if "\\" in url:
        return "contains a backslash, which phones and checkers read differently"
    hidden = JINJA_ANY.sub("\x00", url)
    rest = hidden.split("://", 1)[1] if "://" in hidden else hidden
    head = hidden[:len(hidden) - len(rest)]
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
    if "@" in authority:
        return "has an @ before the path, so the real host is the part after it"
    if "\x00" in head + authority or re.search(r"\{\{|\{%|\}\}|%\}", head + authority):
        return "has Jinja in its scheme or host, so the host is only decided at send time"
    return None


def find_links(text):
    """Links in an SMS, with Jinja kept whole (its spaces would otherwise end the link early)."""
    saved = []

    def hide(m):
        saved.append(m.group(0))
        return f"\x00{len(saved) - 1}\x00"
    hidden = JINJA_ANY.sub(hide, text)
    out = []
    for m in URL_IN_TEXT.finditer(hidden):
        u = re.sub(r"\x00(\d+)\x00", lambda x: saved[int(x.group(1))], m.group(0).rstrip(".,!?;:)'\""))
        out.append(u)
    bare = []
    no_urls = URL_IN_TEXT.sub(" ", hidden)
    for m in re.finditer(r"(?<![\w@./-])(?:[a-z0-9-]+\.)+[a-z]{2,}/\S*", no_urls, re.I):
        bare.append(m.group(0).rstrip(".,!?;:)'\""))
    return out, bare


def check_links(lint, where, text, allowed, hosts_seen):
    links, bare = find_links(text)
    for b in bare:
        lint.block("links", f"{b[:60]!r} has no https://: write every link in full with https://.", where)
    for u in links:
        low = u.lower()
        if low.startswith("http://"):
            lint.block("links", f"Link {u[:60]!r} uses http: links must be https://.", where)
        elif low.startswith("www."):
            lint.block("links", f"Link {u[:60]!r} has no https://: write it in full.", where)
        elif not low.startswith("https://") and "://" in low and not low.startswith(("{{", "{%")):
            lint.block("links", f"Link {u[:60]!r} isn't https://.", where)
        if CUSTOMER_REF.search(u):
            lint.block("link_personal_data", f"Link {u[:60]!r} puts customer data in the URL, which shares it with "
                       "that site and the carrier. Remove it; Bloomreach tracks clicks itself.", where)
        elif "{{" in u or "{%" in u:
            lint.warn("link_jinja", f"Link {u[:60]!r} contains Jinja, so its final form can't be checked before "
                      "rendering: check the rendered link in campaign-qa.", where)
        why = authority_problem(u)
        if why:
            lint.block("link_host_form", f"Link {u[:80]!r} {why}. Write it as https://<supplied host>/<path>.", where)
            continue
        start = JINJA_ANY.sub("", u)
        host = (urlsplit(start if "://" in start else "https://" + start).hostname or "").lower().rstrip(".")
        if not host:
            if start.strip():
                lint.block("links", f"Link {u[:60]!r} has no host that can be checked.", where)
            continue
        hosts_seen.add(host)
        if host_ok(host, RULES["placeholder_hosts"]):
            lint.block("links", f"Link points at a placeholder host ({host}).", where)
        elif not host_ok(host, allowed):
            lint.block("unknown_link_host", f"Link goes to {host}, which isn't a shortener or link host the user "
                       "supplied. Use the user's own domain or shortener, or add the host to user_supplied_hosts if "
                       "the user confirms it's theirs.", where)
        if host in RULES["public_shorteners"]:
            lint.warn("public_shortener", f"{host} is a public link shortener; carriers often filter them. A "
                      "brand-owned shortener is safer.", where)
    return links


def check_message(lint, where, text, draft, regions, allowed, hosts_seen, all_links=None):
    if not text.strip():
        lint.block("message", "The message is empty.", where)
        return {"encoding": None, "chars": 0, "segments": 0, "links": 0}
    for pat in RULES["placeholder_patterns"]:
        m = re.search(pat, text, re.I)
        if m:
            lint.block("placeholder", f"Placeholder or unfinished text left in: {m.group(0)[:40]!r}.", where)
    check_jinja(lint, where, text)
    if not re.search(RULES["opt_out_pattern"], text, re.I):
        msg = "No opt-out wording: end with 'Reply STOP to opt out'."
        if draft.get("transactional") is True:
            lint.warn("opt_out", msg + " (Allowed only because the user says this message is purely transactional.)",
                      where)
        else:
            lint.block("opt_out", msg, where)
    if not re.search(RULES["help_pattern"], text, re.I):
        if draft.get("regulated_industry") is True:
            lint.block("help", "No HELP wording, required for a regulated industry: add 'HELP for help'.", where)
        else:
            lint.warn("help", "No HELP wording: 'Reply HELP for help' is expected by US carriers.", where)
    brand = str(draft.get("brand") or "").strip()
    start = text.lstrip()[:RULES["sms_brand_window_chars"]]
    strict = bool({"US-TX", "CA"} & regions)
    if brand and brand.lower() not in start.lower():
        (lint.block if strict else lint.warn)(
            "brand", f"The message doesn't name {brand!r} in its first {RULES['sms_brand_window_chars']} characters"
            + (" (required for Texas and Canada audiences)." if strict else "."), where)
    links = check_links(lint, where, text, allowed, hosts_seen)
    if all_links is not None:
        all_links.extend(links)
    if "CA" in regions and not links:
        lint.block("casl_contact", "Canada (CASL): no link to a page with the sender's mailing address and contact "
                   "details.", where)
    for cat, terms in sorted(RULES["restricted_terms"].items()):
        hit = [t for t in terms if re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", text, re.I)]
        if hit:
            lint.warn("restricted_content", f"Possible restricted content: {cat} ({', '.join(hit)}); a person should "
                      "judge it. Carrier approval is outside this skill's control.", where)
    seg = segments(text)
    if seg["segments"] > RULES["max_segments"]:
        lint.block("length", f"About {seg['segments']} {seg['encoding']} segments, over the {RULES['max_segments']} "
                   "carriers reassemble. Shorten it.", where)
    elif seg["segments"] > RULES["segments_warning"]:
        lint.warn("length", f"About {seg['segments']} {seg['encoding']} segments ({seg['chars']} characters, each "
                  f"{{{{ }}}} counted as {RULES['jinja_estimate_chars']}); each segment is billed.", where)
    if seg["smart_only"]:
        lint.warn("encoding", "Curly quotes, dashes or an ellipsis force UCS-2, which cuts a segment from "
                  f"{RULES['gsm7_single_chars']} to {RULES['ucs2_single_chars']} characters: use straight ones.", where)
    elif seg["encoding"] == "UCS-2":
        lint.warn("encoding", f"Characters outside GSM-7 ({''.join(seg['non_gsm_chars'][:10])}) make it UCS-2, "
                  f"{RULES['ucs2_single_chars']} characters per single SMS.", where)
    return {"encoding": seg["encoding"], "chars": seg["chars"], "segments": seg["segments"], "links": len(links)}


# ---------- schedule and quiet hours ----------

def parse_offset(text):
    m = OFFSET.match(str(text).strip())
    if not m:
        return None
    h, mi = int(m.group(2)), int(m.group(3))
    if h > 14 or mi > 59:
        return None
    d = dt.timedelta(hours=h, minutes=mi)
    return dt.timezone(-d if m.group(1) == "-" else d)


def window_for(rule, weekday):
    day = "sunday" if weekday == 6 else "saturday" if weekday == 5 else "weekday"
    w = rule.get(day)
    if w is None:
        w = [RULES["federal_window"]["start_hour"], RULES["federal_window"]["end_hour"]]
    return day, w


def in_window(local, w):
    if w == "none":
        return False
    hours = local.hour + local.minute / 60
    return w[0] <= hours < w[1]


MS_THRESHOLD = 10 ** 11  # Unix seconds stay below this until the year 5138; milliseconds are far above it


def unix_seconds(lint, value):
    """schedule.datetime as whole Unix seconds. Milliseconds are converted (with a warning); anything else blocks."""
    try:
        d = Decimal(str(value).strip())
        if not d.is_finite():
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        lint.block("schedule", f"schedule.datetime {str(value)[:30]!r} isn't a Unix time in seconds.", "schedule")
        return None
    if d > MS_THRESHOLD:
        d = d / 1000
        lint.warn("schedule", "schedule.datetime looked like milliseconds, so it was converted to seconds: check the "
                  "local send times.", "schedule")
    ts = int(d)
    if ts != d:
        lint.warn("schedule", "schedule.datetime had a fraction of a second, which was dropped.", "schedule")
    try:
        dt.datetime.fromtimestamp(ts, dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        ts = None
    if ts is None or ts <= 0:
        lint.block("schedule", f"schedule.datetime {str(value)[:30]!r} isn't a usable date.", "schedule")
        return None
    return ts


def check_schedule(lint, draft, regions, explicit_regions, today):
    """The schedule for the payload, and the local send times, checked against quiet hours."""
    sched = draft.get("schedule") or dict(RULES["default_schedule"])
    if not isinstance(sched, dict) or sched.get("type") not in ("now", "datetime"):
        lint.block("schedule", "Use schedule {\"type\": \"now\"} or {\"type\": \"datetime\", \"datetime\": <unix "
                   "seconds>}. Event-triggered SMS belong in a scenario (engagement-scenario-builder).", "schedule")
        return dict(RULES["default_schedule"]), []
    if sched["type"] == "now":
        lint.warn("schedule", "No send time: schedule 'now' means it sends as soon as a person starts it in the "
                  "Engagement UI. Whoever starts it must do so inside quiet-hour limits, or set a time first.",
                  "schedule")
        return {"type": "now"}, []
    ts = unix_seconds(lint, sched.get("datetime"))
    if ts is None:
        return {"type": "now"}, []
    offsets = draft.get("recipient_utc_offsets") or []
    zones = [(o, parse_offset(o)) for o in offsets]
    for o, z in zones:
        if z is None:
            lint.block("schedule", f"Recipient UTC offset {o!r} isn't in the form -05:00.", "schedule")
    zones = [(o, z) for o, z in zones if z is not None]
    if not zones:
        lint.block("schedule", "A fixed send time needs recipient_utc_offsets: the UTC offset, on that date, of every "
                   "time zone the audience covers.", "schedule")
        return {"type": "datetime", "datetime": ts}, []
    us_states = sorted(RULES["state_windows"]) if "US" in regions else sorted(r for r in regions if r in RULES["state_windows"])
    local_times, dates = [], []
    fed = [RULES["federal_window"]["start_hour"], RULES["federal_window"]["end_hour"]]
    for o, z in sorted(zones, key=lambda x: x[1].utcoffset(None)):
        local = dt.datetime.fromtimestamp(ts, z)
        dates.append(local.date())
        local_times.append({"utc_offset": o, "local": local.strftime("%Y-%m-%d %H:%M"), "day": DAYS[local.weekday()]})
        if not in_window(local, fed):
            lint.block("quiet_hours", f"At UTC{o} it sends at {local.strftime('%a %H:%M')}, inside quiet hours "
                       f"(the federal window is {fed[0]}:00-{fed[1]}:00 recipient time). Pick another time.",
                       "schedule")
        for code in us_states:
            rule = RULES["state_windows"][code]
            day, w = window_for(rule, local.weekday())
            if not in_window(local, w):
                allowed = "no sends" if w == "none" else f"{w[0]}:00-{w[1]}:00"
                msg = (f"At UTC{o} it sends at {local.strftime('%a %H:%M')}, outside {rule['name']}'s window on "
                       f"{day}s ({allowed}).")
                if code in explicit_regions:
                    lint.block("state_window", msg + " The audience includes this state.", "schedule")
                else:
                    lint.warn("state_window", msg + " Only matters if recipients can be there.", "schedule")
    if today:
        if all(d < today for d in dates):
            lint.block("schedule", "The send time is in the past.", "schedule")
        elif any(d == today for d in dates):
            lint.warn("schedule", "The send time is today: check it hasn't passed before the draft is started.",
                      "schedule")
    lint.warn("schedule", "A fixed send time applies once a person starts the draft in the Engagement UI; nothing "
              "sends while it's a draft.", "schedule")
    return {"type": "datetime", "datetime": ts}, local_times


def region_notes(lint, regions, assumed):
    if assumed:
        lint.warn("regions", "No regions given, so recipients are assumed to be anywhere in the US and Canada.",
                  "regions")
    states = set(RULES["three_per_day_states"])
    if "US" in regions or states & regions:
        lint.warn("three_per_day", "Florida, Oklahoma and Maryland limit marketing contact to 3 messages per 24 hours "
                  "on one subject: check other sends to this audience.", "regions")
    if "US" in regions or "US-TX" in regions:
        lint.warn("texas_sb140", "Texas: confirm SB 140 registration or exemption, and that numbers are checked "
                  "against the Texas no-call list.", "regions")
    lint.warn("silent_hours", "Loomi Connect can't set silent hours or a throughput policy on an SMS campaign: set "
              "silent hours (recipient time zone) in the Engagement UI before starting it. campaign-qa reports their "
              "absence as a blocker.", "settings")


# ---------- audience, consent, sender ----------

def find_record(paths, rid):
    for r in records(paths):
        if str(r.get("_id") or r.get("id") or "") == str(rid):
            return r
    return None


def build_audience(lint, aud, a):
    if not isinstance(aud, dict) or not aud.get("type"):
        lint.block("audience", "Choose an audience: an existing segment or customer filter.", "audience")
        return None, None
    t = aud["type"]
    if t == "segment":
        sid = aud.get("segmentation_id")
        names = aud.get("segments") or ([aud["segment"]] if aud.get("segment") else [])
        rec = find_record(a.segmentations, sid) if sid else None
        if not rec:
            lint.block("audience", f"Segmentation {sid!r} isn't in the saved search_segmentations details: fetch it "
                       "with segmentation_id first.", "audience")
            return None, None
        if rec.get("archived"):
            lint.block("audience", f"Segmentation '{rec.get('name')}' is archived; choose a live one.", "audience")
        have = [str(s.get("name")) for s in rec.get("segments") or [] if isinstance(s, dict)]
        if not names:
            lint.block("audience", "Name the segment (or segments) to send to.", "audience")
        for n in names:
            if str(n) not in have:
                lint.block("audience", f"Segment {n!r} isn't in segmentation '{rec.get('name')}'.", "audience")
        atoms = [{"type": "attribute", "attribute": {"type": "segmentation", "id": str(sid)},
                  "constraint": {"type": "string", "operator": "equals",
                                 "operands": [{"type": "constant", "value": str(n)}]}} for n in names]
        cf = {"filters": atoms, "formula": "|".join(f"F{i}" for i in range(len(atoms)))}
        return cf, f"segment {', '.join(repr(str(n)) for n in names)} of segmentation '{rec.get('name')}'"
    if t == "customer_filter":
        fid = aud.get("customer_filter_id")
        rec = find_record(a.customer_filters, fid) if fid else None
        if not rec:
            lint.block("audience", f"Customer filter {fid!r} isn't in the saved search_customer_filters details: "
                       "fetch it with customer_filter_id first.", "audience")
            return None, None
        if rec.get("archived"):
            lint.block("audience", f"Customer filter '{rec.get('name')}' is archived; choose a live one.", "audience")
        filters = rec.get("filters")
        if not isinstance(filters, list) or "formula" not in rec:
            lint.block("audience", "The saved customer filter has no filters and formula: fetch its detail.", "audience")
            return None, None
        if not filters:
            lint.warn("audience", f"Customer filter '{rec.get('name')}' is empty, so it matches everyone with consent.",
                      "audience")
        return {"filters": filters, "formula": rec.get("formula") or ""}, f"customer filter '{rec.get('name')}'"
    if t == "everyone":
        if aud.get("confirmed") is not True:
            lint.block("audience", "Sending to everyone needs the user's explicit agreement (confirmed: true).",
                       "audience")
        else:
            lint.warn("audience", "No audience filter: once started, it goes to every customer with SMS consent and "
                      "a phone number.", "audience")
        return None, "everyone with consent (no filter)"
    lint.block("audience", f"Unknown audience type {t!r}: use segment, customer_filter or everyone.", "audience")
    return None, None


def build_consent(lint, draft, path):
    """The consent fields for action, checked against get_consent_settings."""
    settings = load(path)
    if not isinstance(settings, dict):
        fail(f"{path}: expected a get_consent_settings result.")
    cat, general = draft.get("consent_category"), draft.get("general_consent") is True
    if settings.get("enabled") is False:
        lst = draft.get("unsubscribe_list")
        if not lst:
            lint.block("consent", "The consent framework is off in this project: set unsubscribe_list.", "consent")
            return {}
        return {"unsubscribe_list": lst}
    ids = {str(c.get("id")): c for c in settings.get("categories") or [] if isinstance(c, dict)}
    sms_general = (settings.get("general_consent") or {}).get("sms") is True
    if cat and general:
        lint.block("consent", "Set consent_category or general_consent, not both.", "consent")
    if general:
        if not sms_general:
            lint.block("consent", "This project doesn't send SMS under general consent: set a consent_category.",
                       "consent")
        return {"general_consent": True}
    if not cat:
        lint.block("consent", "Set a consent_category: a marketing SMS must only reach customers who agreed to it.",
                   "consent")
        return {}
    if str(cat) not in ids:
        lint.block("consent", f"Consent category {cat!r} isn't in this project's consent settings.", "consent")
    else:
        c = ids[str(cat)]
        if c.get("legitimate_interest"):
            lint.warn("consent", f"Consent category {cat!r} is a legitimate-interest category; marketing texts need "
                      "express consent.", "consent")
        if (c.get("sources") or {}).get("sms_reply") is False:
            lint.warn("consent", f"Consent category {cat!r} doesn't accept SMS replies as a source, so a STOP reply "
                      "may not withdraw it: check with the user.", "consent")
    return {"consent_category": str(cat), "general_consent": False}


def check_sender(lint, draft, campaign_paths):
    s = draft.get("sender") or {}
    name, sid = str(s.get("name") or "").strip(), str(s.get("sender") or "").strip()
    if not name or not sid:
        lint.block("sender", "Set the sender name and sender ID: the default from the senders subcommand, or the "
                   "sender ID the user gives.", "sender")
        return name, sid
    if not SENDER_ID.match(sid):
        lint.block("sender", f"Sender ID {sid!r} must be 1-11 letters and digits (at least one letter) or a phone "
                   "number of 3-17 digits, optionally with +.", "sender")
    if looks_placeholder(name):
        lint.warn("sender", f"The sender name {name!r} looks like a placeholder.", "sender")
    known = list_senders(campaign_paths)
    if any(k["sender"] == sid for k in known):
        if not any(k["sender"] == sid and k["name"] == name for k in known):
            lint.warn("sender", "That sender ID exists, but with a different display name.", "sender")
    elif s.get("source") == "user":
        lint.warn("sender", "No existing SMS campaign uses this sender ID: confirm it's registered with the SMS "
                  "provider, or the send fails.", "sender")
    else:
        lint.block("sender", "That sender ID isn't used by any existing SMS campaign. Use the default from the "
                   "senders subcommand, or one the user gives (source: user).", "sender")
    return name, sid


# ---------- plan ----------

def messages_of(draft):
    """{language: message}, with "" the default language."""
    out = {"": str(draft.get("message") or "")}
    for lang, msg in sorted((draft.get("translations") or {}).items()):
        if str(lang).strip():
            out[str(lang).strip()] = str(msg or "")
    return out


def existing_state(rec):
    a = rec.get("action") or {}
    v = (a.get("variants") or [{}])[0] if isinstance(a.get("variants"), list) else {}
    trs = (v or {}).get("translations") or {}
    fp = a.get("frequency_policy")
    return {"name": rec.get("name"), "schedule": {k: v2 for k, v2 in (rec.get("schedule") or {}).items() if k != "active"},
            "customer_filter": rec.get("customer_filter"),
            "consent_category": a.get("consent_category"), "general_consent": a.get("general_consent"),
            "unsubscribe_list": a.get("unsubscribe_list"),
            "frequency_policy": fp.get("id") if isinstance(fp, dict) else fp,
            "messages": {k: (t or {}).get("message") for k, t in sorted(trs.items())},
            "senders": {k: {"name": ((t or {}).get("sender") or {}).get("name"),
                            "sender": ((t or {}).get("sender") or {}).get("sender")} for k, t in sorted(trs.items())}}


SERVER_KEYS = ("edited", "created")


def clean(rec):
    """The fetched campaign without editor names, server timestamps and schedule.active, for payload and undo."""
    if isinstance(rec, dict):
        out = {k: clean(v) for k, v in rec.items() if not k.endswith("_display_name") and k not in SERVER_KEYS}
        if isinstance(out.get("schedule"), dict):
            out["schedule"].pop("active", None)
        return out
    if isinstance(rec, list):
        return [clean(v) for v in rec]
    return rec


def check_existing(lint, rec, draft, created_id):
    """The draft being revised must be a draft, unlocked, single-variant SMS, and one the skill may touch."""
    if str(draft.get("campaign_id") or "") != str(rec.get("_id") or rec.get("id") or ""):
        lint.block("target", "The draft's campaign_id doesn't match the --existing campaign.", "target")
    if str(rec.get("status") or "").lower() != "draft":
        lint.block("target", f"The campaign's status is {rec.get('status')!r}: this skill only edits drafts, never a "
                   "running, scheduled or stopped campaign.", "target")
    if rec.get("archived"):
        lint.block("target", "The campaign is archived.", "target")
    if rec.get("is_paused"):
        lint.block("target", "The campaign is paused.", "target")
    if rec.get("locked") or rec.get("locked_for_current_user"):
        lint.block("target", "The campaign is locked in Engagement.", "target")
    origin = draft.get("origin")
    rid = str(rec.get("_id") or rec.get("id") or "")
    if origin == "created_this_session" and str(created_id or "") != rid:
        lint.block("target", "origin is created_this_session, but --created-id (the id create_sms_campaign returned "
                   "in this session) is missing or names another campaign. Pass it, or treat the draft as user_named "
                   "and ask the user to confirm it by name.", "target")
    if origin == "user_named":
        if draft.get("user_confirmed") is not True:
            lint.block("target", "A draft this skill didn't create needs the user to confirm it by name "
                       "(user_confirmed: true).", "target")
    elif origin != "created_this_session":
        lint.block("target", "Set origin: created_this_session (made by this skill in this session) or user_named.",
                   "target")
    a = rec.get("action")
    if not isinstance(a, dict) or not isinstance(a.get("variants"), list):
        fail("--existing has no action.variants: pass the search_sms_campaigns detail fetched with campaign_id.")
    if (rec.get("split") or {}).get("type", "off") != "off" or len(a["variants"]) != 1:
        lint.block("target", "The campaign has an A/B split; this skill only edits single-message drafts.", "target")
    elif (a["variants"][0] or {}).get("type") not in (None, "sms"):
        lint.block("target", "The campaign sends MMS; this skill only edits SMS.", "target")


def cmd_plan(a):
    draft = raw_json(a.draft)
    if not isinstance(draft, dict):
        fail(f"{a.draft}: expected a JSON object (references/draft-format.md).")
    today = None
    if a.today:
        try:
            today = dt.date.fromisoformat(a.today)
        except ValueError:
            fail(f"--today {a.today!r} isn't a YYYY-MM-DD date.")
    existing = load(a.existing) if a.existing else None
    if existing is not None and not isinstance(existing, dict):
        fail(f"{a.existing}: expected one search_sms_campaigns campaign_id detail.")
    lint = Lint()
    given = {str(r).strip().upper() for r in draft.get("regions") or [] if str(r).strip()}
    regions = given or set(RULES["assumed_regions"])
    allowed = sorted({str(h).strip().lower() for h in draft.get("user_supplied_hosts") or [] if str(h).strip()})
    name = str(draft.get("name") or "").strip()
    if not name:
        lint.block("name", "The campaign needs a name.", "name")
    for pat in RULES["placeholder_patterns"]:
        m = re.search(pat, name, re.I)
        if m:
            lint.block("placeholder", f"Placeholder text in the name: {m.group(0)[:40]!r}.", "name")
    if not str(draft.get("brand") or "").strip():
        lint.block("brand", "Set the draft's brand: the name every message must open with.", "brand")
    if draft.get("type", "sms") != "sms":
        lint.block("type", "This skill builds SMS only, not MMS.", "type")
    msgs = messages_of(draft)
    hosts_seen, stats, all_links = set(), {}, []
    for lang, text in msgs.items():
        stats[lang] = check_message(lint, "message" + (f" ({lang})" if lang else ""), text, draft, regions, allowed,
                                    hosts_seen, all_links)
    sender_name, sender_id = check_sender(lint, draft, a.campaigns)
    consent = build_consent(lint, draft, a.consent)
    cf, audience_text = build_audience(lint, draft.get("audience"), a)
    schedule, local_times = check_schedule(lint, draft, regions, given, today)
    region_notes(lint, regions, not given)
    fp = draft.get("frequency_policy")

    translations = {lang: {"message": text, "sender": {"name": sender_name, "sender": sender_id}}
                    for lang, text in msgs.items()}
    want = {"name": name, "schedule": schedule, "customer_filter": cf if cf is not None else {"filters": [], "formula": ""},
            "messages": msgs,
            "senders": {lang: {"name": sender_name, "sender": sender_id} for lang in msgs}}
    want.update(consent)
    if fp:
        want["frequency_policy"] = str(fp)

    if existing is None:
        action = dict(consent)
        if fp:
            action["frequency_policy"] = {"id": str(fp)}
        action["variants"] = [{"type": "sms", "translations": translations}]
        payload = {"name": name, "schedule": schedule}
        if cf is not None:
            payload["customer_filter"] = cf
        payload["split"] = {"type": "off"}
        payload["action"] = action
        kind, tool, before, undo = "create", "create_sms_campaign", None, []
        tool_args = {"project_id": a.project_id, "payload": payload}
        target = f"SMS campaign draft '{name}'"
        changed = sorted(k for k in want)
        undo_note = "This skill never deletes. To remove the draft, delete it in the Engagement UI."
    else:
        check_existing(lint, existing, draft, a.created_id)
        old = existing_state(existing)
        payload = clean(existing)
        payload["name"] = name
        payload["schedule"] = dict(schedule)
        if cf is not None:
            payload["customer_filter"] = cf
        elif (draft.get("audience") or {}).get("type") == "everyone":
            payload["customer_filter"] = {"filters": [], "formula": ""}
        act = payload.setdefault("action", {})
        for k in ("consent_category", "general_consent", "unsubscribe_list"):
            if k in consent:
                act[k] = consent[k]
        if consent.get("general_consent") is True:
            act["consent_category"] = None
        if fp:
            act["frequency_policy"] = {"id": str(fp)}
        variants = act.get("variants") or [{}]
        trs = variants[0].setdefault("translations", {})
        for lang, text in msgs.items():
            t = trs.setdefault(lang, {})
            t["message"] = text
            s = t.setdefault("sender", {})
            s["name"], s["sender"] = sender_name, sender_id  # sms and mms provider keys are kept as fetched
        for lang in sorted(set(trs) - set(msgs)):
            lint.warn("translations", f"The draft has a {lang!r} translation this plan doesn't change; it is kept as is.",
                      "message")
        changed = []
        for k in sorted(want):
            new = {**(old.get(k) or {}), **want[k]} if k in ("messages", "senders") else want[k]
            if json.dumps(old.get(k), sort_keys=True) != json.dumps(new, sort_keys=True):
                changed.append(k)
        before = {k: old[k] for k in changed}
        kind, tool = "update", "update_sms_campaign"
        tool_args = {"project_id": a.project_id, "campaign_id": str(existing.get("_id") or existing.get("id")),
                     "payload": payload}
        undo = [{"tool": "update_sms_campaign",
                 "payload": {"project_id": a.project_id, "campaign_id": tool_args["campaign_id"],
                             "payload": clean(existing)}}]
        target = f"SMS campaign draft '{existing.get('name')}' ({tool_args['campaign_id']})"
        undo_note = "The undo puts back the draft exactly as it was fetched, with update_sms_campaign, after a yes."

    after = {k: want[k] for k in changed}
    after["status"] = "draft"
    if lint.problems:
        status = "blocked"
    elif existing is not None and not changed:
        status = "no_change"
    else:
        status = "ready"
    ch = {"n": 1, "status": status, "kind": kind, "target": target, "tool": tool, "payload": tool_args,
          "before": before, "after": after, "expect": want, "undo": undo, "undo_note": undo_note,
          "live_impact": "none",
          "impact_note": "None: it stays a draft. Nothing sends until someone starts it in the Engagement UI.",
          "problems": lint.problems, "warnings": lint.warnings}
    if schedule["type"] == "now":
        sched_text = "now: sends as soon as a person starts it in the Engagement UI"
    else:
        sched_text = "at " + ", ".join(f"{t['local']} ({t['day']}, UTC{t['utc_offset']})" for t in local_times) + \
                     " once a person starts it"
    summary = {"project": a.project_name, "mode": kind, "name": name, "messages": msgs, "message_stats": stats,
               "sender": f"{sender_name} ({sender_id})" if sender_id else None, "audience": audience_text,
               "consent": consent, "schedule": sched_text, "local_send_times": local_times,
               "regions": sorted(regions), "regions_assumed": not given, "link_hosts": sorted(hosts_seen),
               "links": sorted(set(all_links)),
               "changed_fields": changed if existing is not None else None}
    return {"ok": True, "project_id": a.project_id, "project_name": a.project_name, "plan_file": a.out, "changes": [ch],
            "batches": [[1]] if status == "ready" else [], "summary": summary,
            "counts": {"ready": int(status == "ready"), "blocked": int(status == "blocked"),
                       "no_change": int(status == "no_change")}}


# ---------- verify ----------

def numbered_file(text):
    """N=FILE, split on the first "=": a plan change number and its read-back file."""
    n, sep, path = text.partition("=")
    if not sep or not path:
        raise argparse.ArgumentTypeError("use N=FILE, e.g. 1=readback.json")
    try:
        return int(n), path
    except ValueError:
        raise argparse.ArgumentTypeError(f"{n!r} isn't a change number")


def subset(want, have):
    if isinstance(want, dict):
        return isinstance(have, dict) and all(k in have and subset(v, have[k]) for k, v in want.items())
    if isinstance(want, list):
        return isinstance(have, list) and len(want) == len(have) and all(subset(w, h) for w, h in zip(want, have))
    return want == have


def readback(path):
    data = raw_json(path)
    err = tool_error(data)
    if err is not None:
        if CONTEXT_ERROR.search(err):
            context_stop(path, err)
        if not NOT_FOUND.search(err):
            fail(f"{path}: the read-back failed ({redact(err)[:200]}), so nothing was checked. Read it again.")
        return None, redact(err)[:200]
    data = unwrap(data)
    if not isinstance(data, dict):
        fail(f"{path}: expected one search_sms_campaigns campaign_id detail.")
    return data, None


def cmd_verify(a):
    plan = raw_json(a.plan)
    if not isinstance(plan, dict) or not isinstance(plan.get("changes"), list):
        fail(f"{a.plan}: not a plan file (no changes list). Use the file that sms_draft_plan.py plan wrote.")
    by_n = {ch.get("n"): ch for ch in plan["changes"] if isinstance(ch, dict)}
    results = []
    for n, path in sorted(dict(a.readback).items()):
        ch = by_n.get(n)
        if ch is None or ch.get("status") != "ready":
            fail(f"--readback {n}: the plan has no ready change {n}.")
        want = ch.get("expect") or {}
        rec, err = readback(path)
        res = {"n": n, "kind": ch.get("kind"), "target": ch.get("target")}
        if rec is None:
            res.update(state="not_in_place", note=f"The campaign wasn't found ({err}). Before creating it again, list "
                       "search_sms_campaigns and look for its name: a create that errored may still have made it.")
            results.append(res)
            continue
        if not isinstance(rec.get("action"), dict):
            fail(f"{path}: the read-back has no action. Fetch it with search_sms_campaigns and campaign_id.")
        have = existing_state(rec)
        mismatches = []
        planned_id = (ch.get("payload") or {}).get("campaign_id")
        got_id = str(rec.get("_id") or rec.get("id") or "")
        if planned_id and planned_id != got_id:
            mismatches.append({"field": "campaign_id", "planned": planned_id, "found": got_id})
        for k in ("name", "schedule", "consent_category", "frequency_policy"):
            if k in want and json.dumps(want[k], sort_keys=True) != json.dumps(have[k], sort_keys=True):
                mismatches.append({"field": k, "planned": want[k], "found": have[k]})
        if want.get("general_consent") is True and have["general_consent"] is not True:
            mismatches.append({"field": "general_consent", "planned": True, "found": have["general_consent"]})
        for lang, text in sorted((want.get("messages") or {}).items()):
            if have["messages"].get(lang) != text:
                mismatches.append({"field": f"message[{lang!r}]", "planned": "the planned text",
                                   "found": "missing" if have["messages"].get(lang) is None else "different text"})
            if have["senders"].get(lang) != (want.get("senders") or {}).get(lang):
                mismatches.append({"field": f"sender[{lang!r}]", "planned": (want.get("senders") or {}).get(lang),
                                   "found": have["senders"].get(lang)})
        cf, got_cf = want.get("customer_filter"), rec.get("customer_filter")
        if cf is not None and not subset(cf, got_cf):
            mismatches.append({"field": "customer_filter", "planned": cf.get("formula"),
                               "found": (got_cf or {}).get("formula")})
        res["campaign_id"] = got_id
        res["state"] = "not_in_place" if mismatches else "in_place"
        if mismatches:
            res["mismatches"] = mismatches
        if str(rec.get("status") or "").lower() != "draft":
            res["alert"] = (f"The campaign's status is {rec.get('status')!r}, not draft. Tell the user at once; this "
                            "skill never starts campaigns.")
        results.append(res)
    unchecked = sorted(n for n, ch in by_n.items() if ch.get("status") == "ready" and n not in dict(a.readback))
    return {"ok": True, "results": results, "not_checked": unchecked,
            "next": "Run campaign-qa on the draft, and set silent hours in the Engagement UI, before anyone starts it."}


def write_out(path, text):
    if path:
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"{path}: can't write it ({e}).")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # messages can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("senders", help="list the senders existing SMS campaigns use, newest first")
    s.add_argument("--campaigns", action="append", required=True, help="saved search_sms_campaigns detail (repeat)")
    s.add_argument("--out", help="also write the result to this file")
    p = sub.add_parser("plan", help="lint the draft and build the plan")
    p.add_argument("--draft", required=True, help="the draft spec (references/draft-format.md)")
    p.add_argument("--project-id", required=True, help="the Engagement project ID the user confirmed")
    p.add_argument("--project-name", required=True, help="the project's name, shown in the plan")
    p.add_argument("--consent", required=True, help="saved get_consent_settings result")
    p.add_argument("--campaigns", action="append", default=[], help="saved search_sms_campaigns detail (repeat)")
    p.add_argument("--segmentations", action="append", default=[], help="saved search_segmentations detail (repeat)")
    p.add_argument("--customer-filters", action="append", default=[],
                   help="saved search_customer_filters detail (repeat)")
    p.add_argument("--existing", help="saved search_sms_campaigns detail of the draft to revise (makes an update plan)")
    p.add_argument("--today", help="today's date, YYYY-MM-DD, to catch a send time in the past")
    p.add_argument("--out", required=True, help="write the full plan (with the payload) to this file; stdout gets a "
                   "summary without the payload")
    p.add_argument("--created-id", help="the id create_sms_campaign returned in this session, when revising that draft")
    v = sub.add_parser("verify", help="check the read-back after the write")
    v.add_argument("--plan", required=True, help="the plan file from the plan step")
    v.add_argument("--readback", action="append", type=numbered_file, required=True,
                   help="N=FILE: the search_sms_campaigns campaign_id detail after change N")
    v.add_argument("--out", help="also write the result to this file")
    a = ap.parse_args()
    out = {"senders": cmd_senders, "plan": cmd_plan, "verify": cmd_verify}[a.cmd](a)
    text = json.dumps(out, indent=2, ensure_ascii=False)
    write_out(a.out, text)
    if a.cmd == "plan":
        brief = dict(out, changes=[{k: v for k, v in ch.items() if k not in ("payload", "undo", "expect")}
                                   for ch in out["changes"]])
        text = json.dumps(brief, indent=2, ensure_ascii=False)
    print(text)


if __name__ == "__main__":
    main()
