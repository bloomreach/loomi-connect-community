#!/usr/bin/env python3
"""Plan one Bloomreach Engagement email campaign draft before it's created, and check the read-back afterwards.

Usage:
  python3 email_draft_plan.py senders --campaigns detail.json [--campaigns detail.json ...] [--out senders.json]
  python3 email_draft_plan.py plan --draft draft.json --html email.html --project-id ID --project-name NAME
         --consent consent.json --campaigns detail.json [--campaigns ...] [--segmentations detail.json ...]
         [--customer-filters detail.json ...] [--out plan.json]
  python3 email_draft_plan.py verify --plan plan.json --readback 1=readback.json [--out result.json]

senders: lists the senders used by existing email campaigns (saved search_email_campaigns details), newest first.
The first one is the project default this skill uses unless the user names another existing sender.

plan: --draft is the draft spec (references/draft-format.md), --html the email body. --consent is a saved
get_consent_settings result, --campaigns saved search_email_campaigns details (to check the sender exists),
--segmentations and --customer-filters saved detail results for the audience. It lints the draft (unsubscribe
link, postal address, Jinja delimiters and rules, scripts, unknown image hosts and tracking pixels, subject
length, alt text, placeholder text) and prints a plan in the shape in docs/skill-authoring.md ("Plan files for
write skills"), with project_id and project_name in place of account and environment. Any lint blocker makes the
change blocked, with the reasons in problems.

verify: --readback 1=FILE is the search_email_campaigns campaign_id detail, fetched with include_design=true after
the create. Reports the change as in_place or not_in_place. An error about the project, organisation, account or
access stops it.

It never calls Loomi Connect: the assistant makes the one create, after confirmation. Standard library only.
"""
import argparse
import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
NOT_FOUND = re.compile(r"not.?found|does not exist|doesn't exist|no such", re.I)
CONTEXT_ERROR = re.compile(r"\bproject\b|organi[sz]ation|\baccount\b|workspace|permission|\baccess\b|denied|"
                           r"forbidden|unauthori[sz]ed|\b40[13]\b|\b429\b|rate.?limit|too many", re.I)
PAIRS = {"{{": "}}", "{%": "%}", "{#": "#}"}
OPENER = re.compile(r"\{\{|\{%|\{#")
EXPR_OPENER = re.compile(r"\{\{|\{%")
EMBED_TAGS = ("iframe", "embed", "object", "frame", "applet")
RESOURCE_ATTRS = ("src", "poster", "data", "background")
# Comment markers, including Outlook conditional comments, removed so the markup inside them is linted too.
COMMENT_MARKERS = re.compile(r"<!--\[if[^\]]*\]>|<!\[endif\]-->|<!--|-->|<!\[endif\]>?|<!\[if[^\]]*\]>", re.I)
CUSTOMER_REF = re.compile(r"\bcustomer(?:_ids)?\s*(?:\.|\[)")
BLOCK_TAGS = {"for": "endfor", "if": "endif", "macro": "endmacro", "call": "endcall", "filter": "endfilter",
              "raw": "endraw", "with": "endwith", "block": "endblock", "autoescape": "endautoescape"}
MIDDLE_TAGS = {"else": ("if", "for"), "elif": ("if",)}


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(1)


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
    """A tool error about the project, account or access means the call went to the wrong place: stop."""
    fail(f"{path}: Loomi Connect returned an error about the project, account or access ({str(err)[:160]}). "
         "This step couldn't run; check the project and read it again. Don't treat it as 'nothing found'.")


def load(path):
    """A saved tool result, unwrapped from result and data. A success:false result stops the script."""
    data = raw_json(path)
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            err = str(d.get("error") or "no error text")
            if CONTEXT_ERROR.search(err):
                context_stop(path, err)
            fail(f"{path}: the tool returned an error ({err[:200]}). This step couldn't run.")
    if isinstance(data, dict) and isinstance(data.get("result"), (dict, list)):
        data = data["result"]
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], (dict, list)):
        data = data["data"]
    return data


def norm(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def host_ok(host, allowed):
    return any(host == h or host.endswith("." + h) for h in allowed)


# ---------- senders ----------

def campaign_records(paths):
    out = []
    for p in paths:
        doc = load(p)
        for r in doc if isinstance(doc, list) else [doc]:
            if isinstance(r, dict):
                out.append(r)
    return out


def design_datas(rec):
    """Every design.data in a campaign detail: the top-level design and each split variant's."""
    found = []
    for d in [rec.get("design")] + [v.get("design") for v in ((rec.get("split") or {}).get("variants") or [])
                                   if isinstance(v, dict)]:
        if isinstance(d, dict) and isinstance(d.get("data"), dict):
            found.append(d["data"])
    return found


def list_senders(paths):
    seen = {}
    for r in campaign_records(paths):
        if r.get("archived"):
            continue
        keys = {}
        for d in design_datas(r):
            email = str(d.get("sender_email") or "").strip()
            if email:
                keys.setdefault((str(d.get("sender_name") or "").strip(), email.lower()), email)
        for key, email in sorted(keys.items()):
            s = seen.setdefault(key, {"sender_name": key[0], "sender_email": email, "campaigns": 0, "last_edited": 0})
            s["campaigns"] += 1
            try:
                s["last_edited"] = max(s["last_edited"], float(r.get("edited") or 0))
            except (TypeError, ValueError):
                pass
    return sorted(seen.values(), key=lambda s: (-s["last_edited"], -s["campaigns"], s["sender_email"].lower(),
                                                s["sender_name"]))


def cmd_senders(a):
    senders = list_senders(a.campaigns)
    return {"ok": True, "senders": senders, "default": senders[0] if senders else None,
            "note": "Senders from existing, unarchived email campaigns, newest first. The first is the project default "
                    "unless the user names another sender from this list. Don't repeat these addresses in a report."}


# ---------- lint ----------

class Lint:
    def __init__(self):
        self.problems, self.warnings = [], []

    def block(self, check, message, where=None):
        self.problems.append({"check": check, "where": where, "message": message})

    def warn(self, check, message, where=None):
        self.warnings.append({"check": check, "where": where, "message": message})


class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.images, self.scripts, self.handlers, self.resources = [], [], 0, [], []
        self.viewport, self.text, self.link_depth, self.in_style = False, [], 0, False
        self.style_text, self.embeds = [], []
        self.image_hosts, self.link_hosts = set(), set()

    def handle_starttag(self, tag, attrs):
        at = {k.lower(): (v or "") for k, v in attrs}
        for k in at:
            if k.startswith("on"):
                self.handlers.append(f"<{tag} {k}=...>")
        if tag == "script":
            self.scripts += 1
        elif tag == "style":
            self.in_style = True
        elif tag == "a":
            self.links.append(at.get("href"))
            self.link_depth += 1
        elif tag == "img":
            self.images.append(dict(at, _linked=self.link_depth > 0))
        elif tag == "meta" and at.get("name", "").lower() == "viewport":
            self.viewport = True
        elif tag == "link" and at.get("href"):
            self.resources.append(at["href"])
        if tag in EMBED_TAGS:
            self.embeds.append(tag)
        elif tag not in ("a", "link", "base") and at.get("href"):  # VML buttons (v:roundrect), <area>
            self.links.append(at["href"])
        for k in RESOURCE_ATTRS:  # <source src>, <video poster>, <v:fill src>, <td background> ...
            if at.get(k) and not (tag == "img" and k == "src") and tag not in EMBED_TAGS:
                self.resources.append(at[k])
        if at.get("srcset"):
            srcset = at["srcset"]
            if "{{" in srcset or "{%" in srcset:  # commas inside Jinja would split it wrongly
                self.resources.append(srcset)
            else:
                self.resources += [part.split()[0] for part in srcset.split(",") if part.strip()]
        for u in re.findall(r"url\(\s*['\"]?([^'\")\s]+)", at.get("style", "")):
            self.resources.append(u)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag == "a":
            self.link_depth = max(0, self.link_depth - 1)

    def handle_endtag(self, tag):
        if tag == "a":
            self.link_depth = max(0, self.link_depth - 1)
        elif tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.style_text.append(data)
            for u in re.findall(r"url\(\s*['\"]?([^'\")\s]+)", data):
                self.resources.append(u)
            for u in re.findall(r"@import\s+['\"]([^'\"]+)", data):
                self.resources.append(u)
        else:
            self.text.append(data)


def jinja_parts(text):
    """(kind, inner) for each {{ }}, {% %} and {# #} in order, plus the unclosed openers and stray closers."""
    parts, unclosed, i = [], [], 0
    while True:
        m = OPENER.search(text, i)
        if not m:
            parts.append(("text", text[i:]))
            return parts, unclosed
        parts.append(("text", text[i:m.start()]))
        end = text.find(PAIRS[m.group(0)], m.end())
        # A new {{ or {% before this one closes means this one is unclosed (comments may hold anything).
        nxt = None if m.group(0) == "{#" else EXPR_OPENER.search(text, m.end(), len(text) if end == -1 else end)
        if end == -1 or nxt:
            unclosed.append(text[m.start():m.start() + 40])
            i = nxt.start() if nxt else len(text)
            continue
        parts.append((m.group(0), text[m.end():end]))
        i = end + 2


def without_style(html):
    return re.sub(r"<style\b.*?</style\s*>", "", html, flags=re.S | re.I)


def check_jinja(lint, where, text, strict):
    """Delimiters, block tags and the Bloomreach Jinja rules a generated email must follow."""
    parts, unclosed = jinja_parts(text)
    for u in unclosed:
        lint.block("jinja_delimiters", f"Unclosed Jinja delimiter near {u!r}.", where)
    # CSS in <style> can end two rules with "}}", so stray closers are looked for outside it.
    plain = "".join(t for k, t in jinja_parts(without_style(text))[0] if k == "text")
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
                lint.block("jinja_rules", "A recommendations() engine ID must be a quoted string literal, never a "
                           f"variable: {expr[:60]!r}.", where)
            if re.search(r"\baggregates\[\s*[^'\"\s\]]", expr):
                lint.block("jinja_rules", f"An aggregates[...] key must be a quoted string literal: {expr[:60]!r}.", where)
            if re.search(r"\bevent\.", expr):
                lint.block("jinja_rules", "event.* is empty in a campaign that isn't triggered by an event: "
                           f"{expr[:60]!r}.", where)
            for m in re.finditer(r"default\(([^()]*)\)", expr):
                if not re.search(r",\s*true\s*$", m.group(1), re.I):
                    lint.warn("jinja_default", f"| default({m.group(1)}) without true doesn't replace None or '': "
                              "use | default(x, true).", where)
            if kind == "{{" and re.search(r"\bcustomer(\.|\[)", expr) and "default(" not in expr:
                msg = f"{expr[:60]!r} has no fallback, so a customer without it gets None or nothing."
                if strict:
                    lint.block("personalization_fallback", msg, where)
                else:
                    lint.warn("personalization_fallback", msg, where)
    for word, _end in reversed(stack):
        lint.block("jinja_blocks", f"{{% {word} %}} is never closed.", where)
    return parts


def check_placeholders(lint, where, text):
    for pat in RULES["placeholder_patterns"]:
        m = re.search(pat, text, re.I)
        if m:
            lint.block("placeholder", f"Placeholder or unfinished text left in: {m.group(0)[:40]!r}.", where)


def visible_len(text):
    """Length with each {{ ... }} counted as jinja_estimate_chars and {% %} tags dropped."""
    t = re.sub(r"\{%.*?%\}", "", text, flags=re.S)
    t = re.sub(r"\{\{.*?\}\}", "x" * RULES["jinja_estimate_chars"], t, flags=re.S)
    return len(t.strip())


def is_jinja(url):
    return url.strip().startswith(("{{", "{%"))


UPLOAD_HINT = ("Ask the user to upload it to the Engagement media library and give you the URL, or add the host to "
               "user_supplied_hosts if the user says it's theirs.")


def literal_hosts(url):
    """Hosts of the literal http(s) URLs written in a value, including inside Jinja."""
    return sorted({h.lower().rstrip(".") for h in re.findall(r"https?://([A-Za-z0-9.-]+)", url)})


def check_url_host(lint, url, where, allowed, what, seen):
    """An image or other loaded resource must be https on a known or user-supplied host, with no customer data."""
    u = url.strip()
    if not u:
        lint.block("images", f"{what} with an empty source.", where)
        return
    if ("{{" in u or "{%" in u) and CUSTOMER_REF.search(u):
        lint.block("image_personal_data", f"{what} URL {u[:60]!r} carries customer data, which tells that host who "
                   "opened the email (a tracking pixel in effect). Remove the customer reference.", where)
        return
    if is_jinja(u):
        hosts = literal_hosts(u)
        if not hosts:
            seen.add("(from data)")
            lint.warn("images", f"{what} comes from data ({u[:50]!r}); its host can't be checked before rendering.",
                      where)
            return
    else:
        if u.lower().startswith("data:"):
            lint.block("images", f"{what} is embedded as data:, which many email clients block. {UPLOAD_HINT}", where)
            return
        if not u.lower().startswith("https://"):
            lint.block("images", f"{what} {u[:60]!r} isn't a full https:// URL.", where)
        hosts = [(urlsplit(u if "://" in u else "https://" + u.lstrip("/")).hostname or "").lower()]
    for host in hosts:
        seen.add(host)
        if host_ok(host, RULES["placeholder_hosts"]):
            lint.block("images", f"{what} points at a placeholder host ({host}).", where)
        elif not host_ok(host, allowed):
            lint.block("unknown_host", f"{what} is loaded from {host}, which isn't the Bloomreach media library or a "
                       f"host the user supplied. {UPLOAD_HINT}", where)


def check_html(lint, html, draft, allowed):
    p = Parser()
    try:
        p.feed(COMMENT_MARKERS.sub("", html))  # markup in Outlook conditional comments can't hide from the lint
        p.close()
    except Exception as e:  # html.parser is lenient; anything raised means the HTML is unusable
        lint.block("html", f"The HTML couldn't be parsed ({e}).", "body")
        return p
    if p.scripts or re.search(r"<script\b", html, re.I):
        lint.block("script", "The HTML contains <script>. Email clients strip it and spam filters penalise it.", "body")
    for h in sorted(set(p.handlers)):
        lint.block("script", f"Event handler attribute {h}: remove it (JavaScript doesn't run in email).", "body")
    for tag in sorted(set(p.embeds)):
        lint.block("embed", f"<{tag}> embeds another page or object: remove it (email clients block it, and it loads "
                   "content from outside the email).", "body")
    if not p.viewport:
        lint.warn("responsive", "No <meta name=\"viewport\">: the email won't scale on phones. Start from "
                  "assets/starter-email.html.", "body")
    # links
    unsub = False
    for href in p.links:
        h = (href or "").strip()
        low = h.lower()
        if any(t in low.replace(" ", "") for t in RULES["unsubscribe_tokens"]):
            unsub = True
            continue
        if not h or h == "#":
            lint.block("links", "A link has an empty or '#' href.", "body")
        elif low.startswith("javascript:") or low.startswith("data:"):
            lint.block("links", f"A link uses {low.split(':', 1)[0]}:, which isn't a web address.", "body")
        elif low.startswith(("mailto:", "tel:")):
            continue
        elif is_jinja(h):
            pass
        elif low.startswith("http://"):
            lint.warn("links", f"Link {h[:60]!r} uses http, not https.", "body")
        elif not low.startswith("https://"):
            lint.block("links", f"Link {h[:60]!r} has no https://, so it goes nowhere in an inbox.", "body")
        if is_jinja(h):
            hosts = literal_hosts(h)
        elif low.startswith(("http://", "https://")):
            hosts = [(urlsplit(h).hostname or "").lower()]
        else:
            hosts = []
        p.link_hosts.update(hosts)
        for host in hosts:
            if host_ok(host, RULES["placeholder_hosts"]):
                lint.block("links", f"Link points at a placeholder host ({host}).", "body")
        own = bool(hosts) and all(host_ok(x, allowed) for x in hosts)
        if CUSTOMER_REF.search(h) and not own:
            lint.block("link_personal_data", f"Link {h[:60]!r} puts customer data in a URL whose host isn't one the user "
                       "supplied, which shares it with that site. Remove it, or add the host to user_supplied_hosts if "
                       "the user says it's theirs.", "body")
        elif hosts and not own:
            lint.warn("third_party_link", f"Link goes to {', '.join(x for x in hosts if not host_ok(x, allowed))}, which "
                      "isn't a host the user supplied: confirm it with the user.", "body")
    if not unsub:
        lint.block("unsubscribe", "No unsubscribe link: add <a href=\"{{ consent.page }}\"> (consent framework on) or "
                   "<a href=\"{{ email.unsubscribe }}\"> to the footer.", "body")
    # postal address
    low = html.lower()
    by_variable = any(re.search(r"project_variables\.\w*" + re.escape(w), low) for w in RULES["address_variable_words"])
    literal = str(draft.get("postal_address") or "").strip()
    if not by_variable and not (literal and norm(literal) in norm(html)):
        lint.block("postal_address", "No postal address in the footer: use the project variable that holds it "
                   "({{ project_variables.<address variable> }}) or put the address the user gave in postal_address "
                   "and in the HTML.", "body")
    # images
    pixel_max = RULES["tracking_pixel_max_px"]
    for img in p.images:
        src = img.get("src", "")
        try:
            w, h = (int(re.sub(r"px$", "", str(img.get(k, "")).strip()) or 99) for k in ("width", "height"))
        except ValueError:
            w = h = 99
        hidden = re.search(r"display\s*:\s*none", img.get("style", ""), re.I)
        if w <= pixel_max or h <= pixel_max or hidden:
            hosts = literal_hosts(src) if is_jinja(src) else [(urlsplit(src.strip()).hostname or "").lower()]
            hosts = [x for x in hosts if x]
            user_hosts = [str(x).strip().lower() for x in draft.get("user_supplied_hosts") or []]
            if CUSTOMER_REF.search(src) or not hosts or not all(host_ok(x, user_hosts) for x in hosts):
                lint.block("tracking_pixel", f"Tracking pixel from {', '.join(hosts) or 'an unknown host'}: remove it. "
                           "Bloomreach tracks opens itself; only keep a pixel the user supplied.", "body")
            p.image_hosts.update(hosts)
            continue
        check_url_host(lint, src, "body", allowed, "Image", p.image_hosts)
        if "alt" not in img:
            lint.block("alt_text", f"Image {src.strip()[:50]!r} has no alt attribute.", "body")
        elif not img["alt"].strip() and img.get("_linked"):
            lint.warn("alt_text", f"Linked image {src.strip()[:50]!r} has empty alt text, so the link has no label "
                      "when images are off.", "body")
    for r in p.resources:
        check_url_host(lint, r, "body", allowed, "Stylesheet, background or media", p.image_hosts)
    kb = len(html.encode("utf-8")) / 1024
    if kb >= RULES["email_size_warning_kb"]:
        lint.warn("size", f"The HTML is {kb:.0f} KB; Gmail clips emails over about 102 KB, which can hide the "
                  "unsubscribe link.", "body")
    p.kb = round(kb, 1)
    return p


def lint_draft(draft, html):
    lint = Lint()
    allowed = sorted({h.lower() for h in RULES["known_asset_hosts"]} |
                     {str(h).strip().lower() for h in draft.get("user_supplied_hosts") or [] if str(h).strip()})
    name = str(draft.get("name") or "").strip()
    subject = str(draft.get("subject") or "").strip()
    pre = str(draft.get("preheader") or "").strip()
    if not name:
        lint.block("name", "The campaign needs a name.", "name")
    if not subject:
        lint.block("subject", "The subject is empty.", "subject")
    else:
        n = visible_len(subject)
        if n > RULES["subject_blocker_chars"]:
            lint.block("subject", f"The subject is about {n} characters (over {RULES['subject_blocker_chars']}).", "subject")
        elif n > RULES["subject_max_chars"]:
            lint.warn("subject", f"The subject is about {n} characters; inboxes cut it off after about "
                      f"{RULES['subject_max_chars']}.", "subject")
    if not pre:
        lint.warn("preheader", "The preheader is empty, so inboxes show the first body text instead.", "preheader")
    else:
        if visible_len(pre) > RULES["preheader_max_chars"]:
            lint.warn("preheader", f"The preheader is over {RULES['preheader_max_chars']} characters.", "preheader")
        if norm(pre) == norm(subject):
            lint.warn("preheader", "The preheader repeats the subject.", "preheader")
    for where, text, strict in (("name", name, True), ("subject", subject, True), ("preheader", pre, True),
                                ("body", html, False)):
        check_placeholders(lint, where, text)
        if where != "name":
            check_jinja(lint, where, text, strict)
    if not html.strip():
        lint.block("body", "The HTML body is empty.", "body")
        return lint, None
    p = check_html(lint, html, draft, allowed)
    stats = {"subject_chars": visible_len(subject), "preheader_chars": visible_len(pre), "html_kb": getattr(p, "kb", None),
             "images": len(p.images), "links": len(p.links), "allowed_asset_hosts": allowed,
             "image_hosts": sorted(p.image_hosts), "link_hosts": sorted(p.link_hosts)}
    return lint, stats


# ---------- audience, consent, sender ----------

def find_record(paths, rid):
    for p in paths:
        doc = load(p)
        for r in doc if isinstance(doc, list) else [doc]:
            if isinstance(r, dict) and str(r.get("_id") or r.get("id") or "") == str(rid):
                return r
    return None


def build_audience(lint, aud, a):
    """The inline customer_filter for the payload, and a plain description of it."""
    if not isinstance(aud, dict) or not aud.get("type"):
        lint.block("audience", "Choose an audience: an existing segment or customer filter (references/draft-format.md).",
                   "audience")
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
            lint.block("audience", f"Customer filter {fid!r} isn't in the saved search_customer_filters details: fetch "
                       "it with customer_filter_id first.", "audience")
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
            lint.block("audience", "Sending to everyone needs the user's explicit agreement (confirmed: true).", "audience")
        else:
            lint.warn("audience", "No audience filter: once started, it goes to every customer with consent.", "audience")
        return None, "everyone with consent (no filter)"
    lint.block("audience", f"Unknown audience type {t!r}: use segment, customer_filter or everyone.", "audience")
    return None, None


def build_consent(lint, draft, path):
    """The consent fields for the payload, checked against get_consent_settings."""
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
    email_general = ((settings.get("general_consent") or {}).get("email") is True)
    if cat and general:
        lint.block("consent", "Set consent_category or general_consent, not both (the API returns 400).", "consent")
    if general:
        if not email_general:
            lint.block("consent", "This project doesn't send email under general consent: set a consent_category.",
                       "consent")
        return {"general_consent": True}
    if not cat:
        lint.block("consent", "Set a consent_category" + ("" if not email_general else " (or general_consent: true)")
                   + ": the API rejects a campaign with neither.", "consent")
        return {}
    if str(cat) not in ids:
        lint.block("consent", f"Consent category {cat!r} isn't in this project's consent settings.", "consent")
    elif ids[str(cat)].get("legitimate_interest"):
        lint.warn("consent", f"Consent category {cat!r} is a legitimate-interest category; check it suits a "
                  "marketing email.", "consent")
    return {"consent_category": str(cat)}


def check_sender(lint, draft, campaign_paths):
    s = draft.get("sender") or {}
    name, email = str(s.get("name") or "").strip(), str(s.get("email") or "").strip()
    if not name or not email:
        lint.block("sender", "Set the sender name and email: use the project default from the senders subcommand, "
                   "or an existing sender the user names.", "sender")
        return name, email
    known = list_senders(campaign_paths)
    if not known:
        lint.block("sender", "No existing campaign in the saved results has a sender, so the sender can't be checked. "
                   "Pass saved search_email_campaigns details with --campaigns.", "sender")
    elif not any(k["sender_email"].lower() == email.lower() for k in known):
        lint.block("sender", "That sender address isn't used by any existing email campaign. This skill only uses "
                   "a sender that already exists; a new one has to be set up and verified in Engagement first.", "sender")
    elif not any(k["sender_email"].lower() == email.lower() and k["sender_name"] == name for k in known):
        lint.warn("sender", "The sender address exists, but with a different display name.", "sender")
    return name, email


# ---------- plan ----------

def sha(text):
    return hashlib.sha256(text.replace("\r\n", "\n").strip().encode("utf-8")).hexdigest()


def cmd_plan(a):
    draft = raw_json(a.draft)
    if not isinstance(draft, dict):
        fail(f"{a.draft}: expected a JSON object (references/draft-format.md).")
    html = read_text(a.html)
    lint, stats = lint_draft(draft, html)
    sender_name, sender_email = check_sender(lint, draft, a.campaigns)
    consent = build_consent(lint, draft, a.consent)
    cf, audience_text = build_audience(lint, draft.get("audience"), a)
    lint.warn("schedule", "Created with schedule 'now', which sets no send time: whoever starts it in the Engagement "
              "UI must set the send time first, or it sends as soon as it's started.", "schedule")
    if draft.get("frequency_policy"):
        lint.warn("frequency_policy", "A frequency policy is set; check it in the read-back (its format isn't "
                  "documented consistently).", "frequency_policy")

    data = {"sender_name": sender_name, "sender_email": sender_email, "subject": str(draft.get("subject") or "").strip(),
            "preheader": str(draft.get("preheader") or "").strip(), "jinja_html": html}
    payload = {"name": str(draft.get("name") or "").strip(), "schedule": dict(RULES["schedule"])}
    if cf is not None:
        payload["customer_filter"] = cf
    payload.update(consent)
    if draft.get("frequency_policy"):
        payload["frequency_policy"] = {"id": str(draft["frequency_policy"])}
    payload["split"] = {"type": "off", "variants": [{"design": {"type": "raw", "data": data}}]}

    after = {"status": "draft", "name": payload["name"], "schedule_type": RULES["schedule"]["type"],
             "subject": data["subject"], "preheader": data["preheader"], "sender_name": sender_name,
             "sender_email": sender_email, "consent": consent, "customer_filter": cf, "html_sha256": sha(html)}
    status = "blocked" if lint.problems else "ready"
    ch = {"n": 1, "status": status, "kind": "create", "target": f"email campaign draft '{payload['name']}'",
          "tool": "create_email_campaign", "payload": {"project_id": a.project_id, "payload": payload},
          "before": None, "after": after,
          "undo": [],
          "undo_note": "This skill never deletes. To remove the draft, delete it in the Engagement UI.",
          "live_impact": "none",
          "impact_note": "None: created as a draft. Nothing sends until someone starts it in the Engagement UI.",
          "problems": lint.problems, "warnings": lint.warnings}
    summary = {"project": a.project_name, "name": payload["name"], "subject": data["subject"],
               "preheader": data["preheader"], "sender": f"{sender_name} <{sender_email}>" if sender_email else None,
               "audience": audience_text, "consent": consent, "schedule": "none set (draft)",
               "design": "raw HTML (Loomi Connect can't create a Visual Builder design)",
               "image_hosts": (stats or {}).get("image_hosts", []), "link_hosts": (stats or {}).get("link_hosts", [])}
    return {"ok": True, "project_id": a.project_id, "project_name": a.project_name, "changes": [ch],
            "batches": [[1]] if status == "ready" else [], "summary": summary, "stats": stats,
            "counts": {"ready": int(status == "ready"), "blocked": int(status == "blocked"), "no_change": 0}}


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
    """True when every key and list item in want is also in have (the backend may add defaults)."""
    if isinstance(want, dict):
        return isinstance(have, dict) and all(k in have and subset(v, have[k]) for k, v in want.items())
    if isinstance(want, list):
        return isinstance(have, list) and len(want) == len(have) and all(subset(w, h) for w, h in zip(want, have))
    return want == have


def readback(path):
    """(campaign detail, error text). Context errors stop; other errors come back as text."""
    data = raw_json(path)
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            err = str(d.get("error") or "no error text")
            if CONTEXT_ERROR.search(err):
                context_stop(path, err)
            if not NOT_FOUND.search(err):
                fail(f"{path}: the read-back failed ({err[:200]}), so nothing was checked. Read it again.")
            return None, err[:200]
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict):
        fail(f"{path}: expected one search_email_campaigns campaign_id detail.")
    return data, None


def cmd_verify(a):
    plan = raw_json(a.plan)
    if not isinstance(plan, dict) or not isinstance(plan.get("changes"), list):
        fail(f"{a.plan}: not a plan file (no changes list). Use the file that email_draft_plan.py plan wrote.")
    by_n = {ch.get("n"): ch for ch in plan["changes"] if isinstance(ch, dict)}
    results = []
    for n, path in sorted(dict(a.readback).items()):
        ch = by_n.get(n)
        if ch is None or ch.get("status") != "ready":
            fail(f"--readback {n}: the plan has no ready change {n}.")
        want = ch.get("after") or {}
        rec, err = readback(path)
        res = {"n": n, "kind": ch.get("kind"), "target": ch.get("target")}
        if rec is None:
            res.update(state="not_in_place", note=f"The campaign wasn't found ({err}). Before creating it again, "
                       "search_email_campaigns for its name: a create that errored may still have made it.")
            results.append(res)
            continue
        datas = design_datas(rec)
        if not datas or not any("jinja_html" in d for d in datas):
            fail(f"{path}: the read-back has no email body. Fetch it again with search_email_campaigns, campaign_id "
                 "and include_design=true.")
        d = next(x for x in datas if "jinja_html" in x)
        html = str(d.get("jinja_html") or "")
        have = {"status": rec.get("status"), "name": rec.get("name"),
                "schedule_type": (rec.get("schedule") or {}).get("type"), "subject": d.get("subject") or "",
                "preheader": d.get("preheader") or "", "sender_name": d.get("sender_name"),
                "sender_email": d.get("sender_email")}
        mismatches = [{"field": k, "planned": want.get(k), "found": have[k]} for k in sorted(have)
                      if k in want and str(want.get(k) or "") != str(have[k] or "")]
        for k, v in sorted((want.get("consent") or {}).items()):
            if rec.get(k) != v:
                mismatches.append({"field": k, "planned": v, "found": rec.get(k)})
        cf = want.get("customer_filter")
        got_cf = rec.get("customer_filter")
        if cf is None:
            if got_cf and (got_cf.get("filters") or []):
                mismatches.append({"field": "customer_filter", "planned": None, "found": "a filter"})
        elif not subset(cf, got_cf):
            mismatches.append({"field": "customer_filter", "planned": cf.get("formula"),
                               "found": (got_cf or {}).get("formula")})
        if not html.strip():
            mismatches.append({"field": "jinja_html", "planned": "the planned HTML", "found": "empty"})
        elif not any(t in html.lower().replace(" ", "") for t in RULES["unsubscribe_tokens"]):
            mismatches.append({"field": "jinja_html", "planned": "an unsubscribe link", "found": "none"})
        res["campaign_id"] = rec.get("_id") or rec.get("id")
        res["state"] = "not_in_place" if mismatches else "in_place"
        if mismatches:
            res["mismatches"] = mismatches
        res["html_matches"] = sha(html) == want.get("html_sha256")
        if have["status"] != "draft":
            res["alert"] = (f"The campaign's status is {have['status']!r}, not draft. Tell the user at once; this skill "
                            "never starts campaigns.")
        results.append(res)
    unchecked = sorted(n for n, ch in by_n.items() if ch.get("status") == "ready" and n not in dict(a.readback))
    return {"ok": True, "results": results, "not_checked": unchecked,
            "next": "Run campaign-qa on the draft before anyone schedules or starts it."}


def write_out(path, text):
    if path:
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"{path}: can't write it ({e}).")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # briefs and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("senders", help="list the senders existing campaigns use, newest first")
    s.add_argument("--campaigns", action="append", required=True, help="saved search_email_campaigns detail (repeat)")
    s.add_argument("--out", help="also write the result to this file")
    p = sub.add_parser("plan", help="lint the draft and build the plan")
    p.add_argument("--draft", required=True, help="the draft spec (references/draft-format.md)")
    p.add_argument("--html", required=True, help="the email body HTML")
    p.add_argument("--project-id", required=True, help="the Engagement project ID the user confirmed")
    p.add_argument("--project-name", required=True, help="the project's name, shown in the plan")
    p.add_argument("--consent", required=True, help="saved get_consent_settings result")
    p.add_argument("--campaigns", action="append", default=[], help="saved search_email_campaigns detail (repeat)")
    p.add_argument("--segmentations", action="append", default=[], help="saved search_segmentations detail (repeat)")
    p.add_argument("--customer-filters", action="append", default=[], help="saved search_customer_filters detail (repeat)")
    p.add_argument("--out", help="also write the plan to this file")
    v = sub.add_parser("verify", help="check the read-back after the create")
    v.add_argument("--plan", required=True, help="the plan file from the plan step")
    v.add_argument("--readback", action="append", type=numbered_file, required=True,
                   help="N=FILE: the search_email_campaigns campaign_id detail (include_design=true) after change N")
    v.add_argument("--out", help="also write the result to this file")
    a = ap.parse_args()
    out = {"senders": cmd_senders, "plan": cmd_plan, "verify": cmd_verify}[a.cmd](a)
    text = json.dumps(out, indent=2, ensure_ascii=False)
    write_out(a.out, text)
    print(text)


if __name__ == "__main__":
    main()
