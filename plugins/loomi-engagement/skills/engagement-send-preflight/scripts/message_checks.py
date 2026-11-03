#!/usr/bin/env python3
"""Static pre-send checks for Bloomreach Engagement email, SMS and mobile push messages.

Usage:
  python3 message_checks.py detail.json [detail2.json ...] [--node-ids 12,15] [--brand NAME]
         [--regions US,US-TX,CA] [--out findings.json]

Each input is a saved Loomi Connect detail result: search_email_campaigns with campaign_id and
include_design=true, search_sms_campaigns with campaign_id, search_scenarios with scenario_id and
include_node_designs=true, or one node from search_scenario_nodes with include_design=true.
--node-ids limits scenario inputs to those send steps. --brand is the brand name SMS should open
with. --regions lists where recipients can be (CA turns on the Canada checks, US-TX the Texas ones).

Checks every email, SMS and push message (each A/B variant and translation) for things that
don't need a web request or a customer profile: placeholder merge tags, Jinja that won't parse,
personalization with no fallback, unguarded aggregate loops, link problems (missing scheme, http,
placeholder destinations, near-miss hosts, public shorteners), unsubscribe, postal address,
consent, subject and preheader, alt text, size, spam score, SMS opt-out, brand and segments,
push title and body. Links still have to be loaded, and Jinja rendered against sample profiles,
by the assistant: links_to_load lists the unique URLs, primary ones first.

Thresholds and word lists are in references/rules.json. Standard library only; no network access.
"""
import argparse
import json
import math
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

# The thresholds live in references/rules.json, next to this script's folder.
RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
SEVERITIES = ("blocker", "warning", "nitpick")
CHECKED_NODES = {"send-email-action": "email", "send-sms-action": "sms", "push-notification-mobile-action": "push"}
SEND_HINTS = ("send-", "push", "whatsapp", "rcs", "inbox", "webhook", "mms")
JINJA_EXPR = re.compile(r"\{\{.*?\}\}", re.S)
JINJA_TAG = re.compile(r"\{%-?\s*(\w+)(.*?)-?%\}", re.S)
BLOCKS = {"if": "endif", "for": "endfor", "macro": "endmacro", "call": "endcall", "filter": "endfilter",
          "raw": "endraw", "with": "endwith", "block": "endblock", "set": "endset"}
GSM7 = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§"
           "¿abcdefghijklmnopqrstuvwxyzäöñüà")
GSM7_EXT = set("^{}\\[~]|€\f")
SMART = set("‘’“”–—…")


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {d.get('error') or 'no error text'}. "
                 "This check couldn't run; don't treat it as 'nothing found'.")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], (dict, list)):
        data = data["data"]
    if isinstance(data, list):
        fail(f"{path}: this is a list result. Fetch one campaign or scenario by ID and pass that.")
    return data


# ----------------------------------------------------------------------------------------------
# Extract messages from the different result shapes

def email_message(base, design, variant=None):
    d = (design or {}).get("data") or {}
    return dict(base, channel="email", variant=variant, subject=d.get("subject") or "",
                preheader=d.get("preheader") or "", html=d.get("jinja_html"),
                sender_name=d.get("sender_name") or "", sender_email=d.get("sender_email") or "")


def sms_messages(base, translations, max_parts, variant=None):
    out = []
    for lang, t in (translations or {}).items():
        sender = (t or {}).get("sender") or {}
        out.append(dict(base, channel="sms", variant=variant, language=lang or None,
                        text=(t or {}).get("message") or "", sender_name=sender.get("name") or "",
                        max_message_parts=max_parts))
    return out


def push_message(base, node):
    try:
        data = json.loads(node.get("data") or "{}")
    except ValueError:
        data = {}
    return dict(base, channel="push", title=data.get("title") or "",
                body=data.get("message") or data.get("body") or "", action=data.get("action"),
                url=data.get("url") or data.get("deeplink") or "", image=data.get("image") or "")


def settings(obj):
    return {"consent_category": obj.get("consent_category"), "general_consent": bool(obj.get("general_consent")),
            "frequency_policy": obj.get("frequency_policy")}


def extract(data, node_ids):
    """Return (source, messages, not_checked) for one saved detail result."""
    msgs, skipped = [], []
    if "nodes" in data or data.get("type") in CHECKED_NODES or "-action" in str(data.get("type", "")):
        nodes = data.get("nodes") if "nodes" in data else [data]
        for n in nodes:
            t = n.get("type", "")
            if node_ids and n.get("id") not in node_ids:
                continue
            base = dict(settings(n), source="scenario", id=n.get("id"), parent_id=data.get("_id"), name=n.get("name") or "",
                        schedule=None, silent_hours="flow")
            if t == "send-email-action":
                if "jinja_html" not in ((n.get("design") or {}).get("data") or {}):
                    fail("The email design was stripped. Fetch the scenario with include_node_designs=true "
                         "(or the node with include_design=true).")
                msgs.append(email_message(base, n.get("design")))
            elif t == "send-sms-action":
                tr = n.get("translations") or ({"": n["content"]} if n.get("content") else {})
                msgs += sms_messages(base, tr, n.get("max_message_parts"))
            elif t == "push-notification-mobile-action":
                msgs.append(push_message(base, n))
            elif any(h in t for h in SEND_HINTS):
                skipped.append({"id": n.get("id"), "name": n.get("name") or "", "type": t})
        return "scenario", msgs, skipped
    sched = data.get("schedule") or {}
    if isinstance(data.get("action"), dict) and "variants" in data["action"]:
        a = data["action"]
        base = dict(settings(a), source="sms_campaign", id=data.get("_id"), parent_id=data.get("_id"), name=data.get("name") or "",
                    schedule=sched.get("type"),
                    silent_hours=data.get("silent_hours") or data.get("throughput_policy") or a.get("throughput_policy_id"))
        for v in a["variants"]:
            name = v.get("name") or (f"variant {v.get('id')}" if len(a["variants"]) > 1 else None)
            msgs += sms_messages(base, v.get("translations"), v.get("max_message_parts"), name)
        return "sms_campaign", msgs, skipped
    if "design" in data or "split" in data:
        base = dict(settings(data), source="email_campaign", id=data.get("_id"), parent_id=data.get("_id"), name=data.get("name") or "",
                    schedule=sched.get("type"), silent_hours=data.get("silent_hours"))
        variants = ((data.get("split") or {}).get("variants")) or []
        if any("jinja_html" not in ((v.get("design") or {}).get("data") or {}) for v in variants) or \
                (not variants and "jinja_html" not in ((data.get("design") or {}).get("data") or {})):
            fail("The email design was stripped. Fetch the campaign again with include_design=true.")
        if variants:
            msgs += [email_message(base, v.get("design"), v.get("name")) for v in variants]
        else:
            msgs.append(email_message(base, data.get("design")))
        return "email_campaign", msgs, skipped
    fail("Not a campaign, scenario or scenario node detail result.")


# ----------------------------------------------------------------------------------------------
# HTML

class EmailHTML(HTMLParser):
    """Collects links, images and visible text from an email's HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.images, self.text, self.hidden_text = [], [], [], []
        self._a = None
        self._skip = 0
        self._hidden = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        style = (a.get("style") or "").replace(" ", "").lower()
        if tag in ("script", "style", "title"):
            self._skip += 1
        if tag not in ("br", "img", "meta", "link", "hr", "input"):
            # None: no font size here; True: font-size 0. BEE sets 0 on layout cells and resets it inside.
            size = re.search(r"font-size:([\d.]+)", style)
            self._hidden.append(None if not size else float(size.group(1)) == 0)
        if tag == "a":
            self._a = {"href": a.get("href"), "text": "", "style": style, "class": a.get("class") or "",
                       "has_img": False}
            self.links.append(self._a)
        elif tag == "img":
            self.images.append({"src": a.get("src") or "", "alt": a.get("alt"), "linked": self._a is not None})
            if self._a is not None:
                self._a["has_img"] = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "title"):
            self._skip = max(0, self._skip - 1)
        if tag == "a":
            self._a = None
        if tag not in ("br", "img", "meta", "link", "hr", "input") and self._hidden:
            self._hidden.pop()

    def handle_data(self, data):
        if self._skip:
            return
        sizes = [h for h in self._hidden if h is not None]
        (self.hidden_text if sizes and sizes[-1] else self.text).append(data)
        if self._a is not None:
            self._a["text"] += data


def visible_text(parts):
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


# ----------------------------------------------------------------------------------------------
# Checks

class Report:
    def __init__(self):
        self.findings = []

    def add(self, severity, check, message, where=None, evidence=None):
        f = {"severity": severity, "check": check, "message": message}
        if where:
            f["where"] = where
        if evidence:
            f["evidence"] = evidence[:160]
        self.findings.append(f)


def placeholder_checks(rep, fields):
    pats = [re.compile(p, re.I) for p in RULES["placeholder_tokens"]]
    for where, text in fields:
        for p in pats:
            m = p.search(text or "")
            if m:
                rep.add("blocker", "placeholder", "Unfinished copy or a merge tag from another tool; customers would see it as written",
                        where, m.group(0))


def jinja_checks(rep, fields, schedule):
    for where, text in fields:
        if not text:
            continue
        # Only unclosed openers count: CSS in email HTML is full of "}}" and "%}".
        rest = re.sub(r"\{%.*?%\}", "", JINJA_EXPR.sub("", text), flags=re.S)
        if "{{" in rest or "{%" in rest:
            i = min(x for x in (rest.find("{{"), rest.find("{%")) if x >= 0)
            rep.add("blocker", "jinja_syntax", "Unclosed Jinja delimiter ({{ or {%); the template won't render", where, rest[i:i + 60])
        stack = []
        for m in JINJA_TAG.finditer(text):
            tag = m.group(1)
            if tag in BLOCKS and (tag != "set" or "=" not in m.group(2)):  # only {% set x %}...{% endset %} is a block
                stack.append(tag)
            elif tag.startswith("end"):
                if not stack or BLOCKS.get(stack[-1]) != tag:
                    rep.add("blocker", "jinja_syntax", f"'{{% {tag} %}}' doesn't close an open block", where)
                    stack = []
                    break
                stack.pop()
        else:
            if stack:
                rep.add("blocker", "jinja_syntax", f"'{{% {stack[-1]} %}}' is never closed", where)
        for m in re.finditer(r"\|\s*default\(([^()]*(?:\([^()]*\)[^()]*)*)\)", text):
            if not re.search(r",\s*(true|True)\s*$", m.group(1)):
                rep.add("warning", "default_without_true",
                        "default(x) only replaces undefined values; add true so None and '' are replaced too: default(x, true)",
                        where, m.group(0))
        strong = where in ("subject", "preheader", "push title") or where.startswith("sms")
        for expr in sorted(set(re.findall(r"\{\{[^}]*\bcustomer(?:\.|\[)[^}]*\}\}", text))):
            if "default(" not in expr:
                rep.add("warning" if strong else "nitpick", "no_fallback",
                        "Customer property with no fallback prints None for customers without it; "
                        "render against a sparse profile (a blocker if it breaks the subject or first line)",
                        where, expr)
        for m in re.finditer(r"\{%-?\s*for\s+\w+\s+in\s+([\w.]+(?:\[[^\]]+\])?)", text):
            src = m.group(1)
            before = text[max(0, m.start() - 400):m.start()]
            agg = src.startswith("aggregates")
            if not agg:
                setm = re.search(r"\{%-?\s*set\s+" + re.escape(src) + r"\s*=\s*aggregates\[", text[:m.start()])
                agg = bool(setm)
            if agg and "'None'" not in before and '"None"' not in before:
                rep.add("warning", "unguarded_aggregate",
                        "Loop over an aggregate with no guard: an empty aggregate renders as the string 'None', "
                        "so the loop runs over its letters. Wrap it in {% if x and x != 'None' %}", where, m.group(0))
        if schedule in ("now", "planned", "repeated", "repeat") and re.search(r"\bevent\.\w+", text):
            rep.add("blocker", "event_without_trigger",
                    "References event.* but the campaign isn't triggered by an event, so it renders empty", where,
                    re.search(r"\bevent\.[\w.]+", text).group(0))


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def host_of(url):
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def near_misses(hosts):
    """Map a suspicious host to the host it probably should be."""
    counts = Counter(h for h in hosts if h)
    out = {}
    names = sorted(counts)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            sa, sb = a.rsplit(".", 1)[0], b.rsplit(".", 1)[0]
            same_name = sa == sb and a != b
            close = min(len(a), len(b)) > 5 and 0 < edit_distance(a, b) <= RULES["near_miss_max_edits"]
            if same_name or close:
                odd, good = (a, b) if counts[a] < counts[b] or (counts[a] == counts[b] and a > b) else (b, a)
                out[odd] = good
    return out


def link_checks(rep, links, channel, all_hosts):
    """links: [{"url", "primary", "where"}]. Returns the URLs to load."""
    to_load = []
    miss = near_misses(all_hosts)
    words = set(RULES["placeholder_words"])
    tokens = [re.compile(p, re.I) for p in RULES["placeholder_tokens"]]
    for l in links:
        url, primary, where = (l["url"] or "").strip(), l["primary"], l["where"]
        sev = "blocker" if primary else "warning"
        low = url.lower()
        if low.startswith(("mailto:", "tel:", "sms:")):
            continue
        if any(t.search(url) for t in tokens):
            rep.add("blocker", "placeholder", "Link is a merge tag from another tool or a placeholder", where, url)
            continue
        if url.startswith(("{{", "{%")):
            l["needs_render"] = True
            continue
        if url in ("", "#") or low.startswith("#"):
            rep.add(sev, "placeholder_link", "Link goes nowhere (empty or '#')", where, url or "(empty)")
            continue
        if channel == "sms" and low.startswith("www."):
            url, low = "https://" + url, "https://" + low
        if not re.match(r"[a-z][a-z0-9+.-]*:", low) and not low.startswith("//"):
            rep.add(sev, "missing_scheme", "Link has no https:// so it's treated as a relative link and goes nowhere", where, url)
            continue
        if low.startswith("http://"):
            rep.add("warning", "no_tls", "Link uses http://, not https://", where, url)
        host = host_of(url)
        if any(host == h or host.endswith("." + h) for h in RULES["placeholder_hosts"]):
            rep.add(sev, "placeholder_link", "Link points at a placeholder host", where, url)
        else:
            parts = urlsplit(url)
            hit = sorted(words & set(re.split(r"[^a-z0-9]+", (parts.path + " " + parts.query).lower())))
            if hit:
                rep.add("warning", "placeholder_words", f"Link path looks like a placeholder ({', '.join(hit)}); confirm the real URL",
                        where, url)
        if host in miss:
            rep.add(sev, "near_miss_host", f"Host {host} is a near miss of {miss[host]}, used elsewhere in this message", where, url)
        if channel == "sms" and host in RULES["public_shorteners"]:
            rep.add("warning", "public_shortener", "Public link shortener; carriers often filter these. Use a brand-owned domain",
                    where, url)
        if "{{" not in url and "{%" not in url:
            to_load.append({"url": url, "primary": primary})
        else:
            l["needs_render"] = True
    return to_load


def spam_score(subject, body, links):
    reasons, score = [], 0
    caps = [w for w in re.findall(r"\b[A-Za-z]+\b", subject)
            if len(w) >= RULES["spam_caps_word_min_len"] and w.isupper()]
    if caps:
        score += len(caps)
        reasons.append(f"all-caps words in the subject: {', '.join(caps[:5])}")
    if re.search(r"!{2,}|\${2,}", subject):
        score += 2
        reasons.append("repeated ! or $ in the subject")
    for where, text, weight in (("subject", subject, 2), ("body", body, 1)):
        found = [p for p in RULES["spam_phrases"] if re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", text, re.I)]
        if found:
            score += weight * len(found)
            reasons.append(f"trigger phrases in the {where}: {', '.join(found[:6])}")
    emoji = len(re.findall("[\U0001F300-\U0001FAFF☀-➿]", subject))
    if emoji > 3:
        score += 1
        reasons.append(f"{emoji} emoji in the subject")
    for l in links:
        shown = re.search(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})\b", (l.get("text") or "").lower())
        href = host_of(l.get("href") or "")
        if shown and href and "{{" not in (l.get("href") or "") and not href.endswith(shown.group(1)) \
                and not shown.group(1).endswith(href):
            score += 3
            reasons.append(f"link text shows {shown.group(1)} but points to {href}")
    level = "high" if score >= RULES["spam_high_score"] else "medium" if score >= RULES["spam_medium_score"] else "low"
    return {"score": score, "level": level, "reasons": reasons}


ADDRESS = [r"\b\d{1,6}\s+[\w .'-]{2,40}\b(?:street|st|road|rd|avenue|ave|boulevard|blvd|lane|ln|drive|dr|way|plaza|square|sq|place|pl|court|ct|suite|ste)\b",
           r"\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b", r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", r"\bP\.?\s?O\.?\s+Box\b"]


def check_email(rep, m, regions):
    html = m["html"] or ""
    p = EmailHTML()
    p.feed(html)
    text = visible_text(p.text)
    subject, pre = m["subject"].strip(), m["preheader"].strip()
    if not subject:
        rep.add("blocker", "subject_missing", "No subject line", "subject")
    elif len(estimate(subject)) > RULES["subject_max_chars"]:
        rep.add("nitpick", "subject_length", f"Subject is about {len(estimate(subject))} characters; inboxes cut it around "
                f"{RULES['subject_max_chars']}", "subject", subject)
    if not pre:
        rep.add("warning", "preheader_missing", "Preheader is empty, so inboxes show the first body text instead", "preheader")
    elif len(pre) > RULES["preheader_max_chars"]:
        rep.add("nitpick", "preheader_length", f"Preheader is {len(pre)} characters", "preheader", pre)
    elif pre.lower() == subject.lower():
        rep.add("nitpick", "preheader_repeats_subject", "Preheader repeats the subject", "preheader", pre)
    low = html.lower()
    unsub = "email.unsubscribe" in low or "consent.page" in low or any(
        re.search(r"unsubscribe|opt[\s-]?out|preferences", (l.get("text") or "") + " " + (l.get("href") or ""), re.I) for l in p.links)
    if not unsub:
        rep.add("blocker", "unsubscribe_missing", "No unsubscribe or preference-centre link", "body")
    if not ("project_variables" in low and "address" in low) and not any(re.search(a, text, re.I if i == 0 else 0)
                                                                         for i, a in enumerate(ADDRESS)):
        rep.add("warning", "address_not_found",
                "No postal address found in the text. A missing address is a blocker (CAN-SPAM); check the footer, "
                "it may be in a format this check doesn't recognise", "body")
    if "email.view" not in low and not re.search(r"view (?:it )?(?:in (?:your|a) browser|online)|web version", text, re.I):
        rep.add("nitpick", "view_online_missing", "No view-in-browser link", "body")
    if "CA" in regions and not (re.search(r"mailto:|tel:", low) or re.search(r"\+?\d[\d ().-]{8,}\d", text)
                                or any(re.search(r"contact", (l.get("text") or "") + (l.get("href") or ""), re.I) for l in p.links)):
        rep.add("blocker", "casl_contact", "Canada (CASL): no phone number, email address or contact link for the sender", "body")
    if not m["sender_name"] or not m["sender_email"]:
        rep.add("warning", "sender_missing", "Sender name or email isn't set on the message; confirm the project default applies", "settings")
    no_alt = [i for i in p.images if i["alt"] is None]
    first = p.images[0]["src"] if p.images else None
    key = [i for i in no_alt if i["linked"] or i["src"] == first]
    if key:
        rep.add("warning", "alt_missing", f"{len(key)} linked or hero image(s) have no alt text", "body", key[0]["src"])
    if len(no_alt) > len(key):
        rep.add("nitpick", "alt_missing", f"{len(no_alt) - len(key)} other image(s) have no alt text", "body")
    if p.images and len(re.sub(r"\{\{.*?\}\}|\{%.*?%\}", "", text)) < RULES["min_text_chars"]:
        rep.add("warning", "image_only", f"Almost no text ({len(text)} characters) next to {len(p.images)} image(s); image-only emails "
                "land in spam more often", "body")
    kb = len(html.encode("utf-8")) / 1024
    if kb >= RULES["email_size_warning_kb"]:
        rep.add("warning", "size", f"HTML is {kb:.0f} KB; Gmail clips emails over about 102 KB, which can hide the unsubscribe link", "body")
    elif kb >= RULES["email_size_nitpick_kb"]:
        rep.add("nitpick", "size", f"HTML is {kb:.0f} KB, close to Gmail's 102 KB clipping limit", "body")
    hrefs = {l["href"] for l in p.links if l.get("href")}
    if len(hrefs) > RULES["max_unique_links"]:
        rep.add("nitpick", "many_links", f"{len(hrefs)} unique links", "body")
    hidden = visible_text(p.hidden_text)
    spam = spam_score(subject, text, p.links)
    if len(hidden) > 20:
        spam["score"] += 2
        spam["reasons"].append("text hidden with font-size 0")
        spam["level"] = "high" if spam["score"] >= RULES["spam_high_score"] else "medium" if spam["score"] >= RULES["spam_medium_score"] else "low"
    if spam["level"] == "high":
        rep.add("warning", "spam_risk", "High spam risk: " + "; ".join(spam["reasons"]), "subject and body")
    first_img_link = next((l for l in p.links if l["has_img"]), None)
    links = []
    for l in p.links:
        primary = l is first_img_link or "button" in l["class"].lower() or "btn" in l["class"].lower() or "background-color" in l["style"]
        links.append({"url": l.get("href") or "", "primary": primary, "where": "body", "text": (l.get("text") or "").strip()[:60]})
    for i in p.images:
        links.append({"url": i["src"], "primary": i["src"] == first, "where": "image"})
    fields = [("subject", subject), ("preheader", pre), ("body", html)]
    return fields, links, {"text_chars": len(text), "images": len(p.images), "unique_links": len(hrefs), "html_kb": round(kb, 1),
                           "spam": spam}


def estimate(text):
    """Text with each {{ }} counted as jinja_estimate_chars characters and {% %} tags dropped."""
    return re.sub(r"\{%.*?%\}", "", JINJA_EXPR.sub("x" * RULES["jinja_estimate_chars"], text), flags=re.S)


def sms_segments(text):
    est = estimate(text)
    gsm = all(c in GSM7 or c in GSM7_EXT for c in est)
    if gsm:
        n = sum(2 if c in GSM7_EXT else 1 for c in est)
        segs = 1 if n <= 160 else math.ceil(n / 153)
    else:
        n = len(est.encode("utf-16-le")) // 2
        segs = 1 if n <= 70 else math.ceil(n / 67)
    return {"encoding": "GSM-7" if gsm else "UCS-2", "chars": n, "segments": segs,
            "smart_only": not gsm and all(c in GSM7 or c in GSM7_EXT or c in SMART for c in est)}


def check_sms(rep, m, regions, brand):
    text = m["text"]
    where = "sms" + (f" ({m['language']})" if m.get("language") else "")
    if not text.strip():
        rep.add("blocker", "sms_empty", "Message body is empty", where)
        return [], [], {}
    if not re.search(r"\bstop\b|opt[\s-]?out|unsubscribe", text, re.I):
        rep.add("blocker", "sms_opt_out", "No opt-out language. Add 'Reply STOP to opt out' (ignore only if this is purely transactional)", where)
    if not re.search(r"\bhelp\b", text, re.I):
        rep.add("nitpick", "sms_help", "No HELP language", where)
    start = text.lstrip()[:RULES["sms_brand_window_chars"]]
    if brand:
        branded = brand.lower() in start.lower()
    else:
        branded = bool(re.match(r"\s*(\{\{[^}]*\}\}|[^\s:{}][^:\n]{0,30})\s*:", start))
    if not branded:
        strict = "US-TX" in regions or "CA" in regions
        rep.add("blocker" if strict else "warning", "sms_brand",
                "Doesn't open with the brand name" + (" (required for Texas and Canada audiences)" if strict else ""), where, start)
    if "CA" in regions and not re.search(r"https?://|www\.", text):
        rep.add("blocker", "casl_contact", "Canada (CASL): no link to a page with the sender's mailing address and contact details", where)
    for cat, terms in RULES["restricted_terms"].items():
        hit = [t for t in terms if re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", text, re.I)]
        if hit:
            rep.add("warning", "restricted_content", f"Possible restricted content: {cat} ({', '.join(hit)}); a person should judge it", where)
    seg = sms_segments(text)
    if m.get("max_message_parts") and seg["segments"] > m["max_message_parts"]:
        rep.add("warning", "sms_length", f"About {seg['segments']} {seg['encoding']} segments, over the step's limit of "
                f"{m['max_message_parts']}", where)
    if seg["smart_only"]:
        rep.add("nitpick", "sms_encoding", "Curly quotes or dashes force UCS-2, which halves the characters per segment", where)
    if m["source"] == "sms_campaign" and not m.get("silent_hours"):
        rep.add("blocker", "sms_quiet_hours", "No silent hours or time-restricted throughput policy: marketing SMS must be held to "
                "8 a.m.-9 p.m. recipient time (9 a.m.-8 p.m. covers every US state)", "settings")
    links = [{"url": u.rstrip(".,!?)"), "primary": i == 0, "where": where}
             for i, u in enumerate(re.findall(r"(?:https?://|www\.)[^\s<>\"]+", text))]
    return [(where, text)], links, seg


def check_push(rep, m):
    if not m["body"].strip():
        rep.add("blocker", "push_empty", "Push body is empty", "push body")
    elif len(m["body"]) > RULES["push_body_max_chars"]:
        rep.add("nitpick", "push_length", f"Body is {len(m['body'])} characters and likely to be truncated", "push body")
    if len(m["title"]) > RULES["push_title_max_chars"]:
        rep.add("nitpick", "push_length", f"Title is {len(m['title'])} characters and likely to be truncated", "push title")
    if m.get("action") in ("browser", "deeplink") and not m.get("url"):
        rep.add("blocker", "push_link", f"Tap action is '{m['action']}' but there's no URL", "push action")
    links = [{"url": m["url"], "primary": True, "where": "push action"}] if m.get("url") else []
    if m.get("image"):
        links.append({"url": m["image"], "primary": False, "where": "push image"})
    return [("push title", m["title"]), ("push body", m["body"])], links, {}


def check_message(m, regions, brand, all_hosts):
    rep = Report()
    if m["channel"] == "email":
        fields, links, stats = check_email(rep, m, regions)
    elif m["channel"] == "sms":
        fields, links, stats = check_sms(rep, m, regions, brand)
    else:
        fields, links, stats = check_push(rep, m)
    visible = [(w, re.sub(r"<[^>]+>", " ", t) if w == "body" else t) for w, t in fields]
    placeholder_checks(rep, visible)
    jinja_checks(rep, fields, m.get("schedule"))
    if not m.get("consent_category") and not m.get("general_consent"):
        rep.add("blocker" if m["channel"] != "push" else "warning", "consent_missing", "No consent category on the message", "settings")
    if m.get("frequency_policy") == "unlimited-policy":
        rep.add("nitpick", "frequency_unlimited", "Frequency policy is unlimited, so nothing caps how many messages a customer gets",
                "settings")
    to_load = link_checks(rep, links, m["channel"], all_hosts)
    order = {s: i for i, s in enumerate(SEVERITIES)}
    seen, findings = set(), []
    for f in sorted(rep.findings, key=lambda f: order[f["severity"]]):
        k = (f["severity"], f["check"], f.get("where"), f.get("evidence"))
        if k not in seen:
            seen.add(k)
            findings.append(f)
    return findings, to_load, [l["url"] for l in links if l.get("needs_render")], stats


def message_hosts(m):
    if m["channel"] == "email":
        urls = re.findall(r"(?:href|src)=[\"']([^\"']+)", m["html"] or "")
    elif m["channel"] == "sms":
        urls = re.findall(r"https?://[^\s<>\"]+", m["text"])
    else:
        urls = [m.get("url") or "", m.get("image") or ""]
    return [host_of(u) for u in urls if u.lower().startswith(("http://", "https://"))]


def verdict(counts):
    return "NO-GO" if counts["blocker"] else "GO WITH CAUTION" if counts["warning"] else "GO"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="saved campaign, scenario or scenario node detail results")
    ap.add_argument("--node-ids", help="comma-separated scenario node IDs to check (default: every send step)")
    ap.add_argument("--brand", help="brand name each SMS should open with")
    ap.add_argument("--regions", default="", help="comma-separated places recipients can be, e.g. US,US-TX,CA")
    ap.add_argument("--out", help="also write the JSON result to this file")
    a = ap.parse_args()
    node_ids = {int(x) for x in a.node_ids.split(",") if x.strip()} if a.node_ids else None
    regions = {r.strip().upper() for r in a.regions.split(",") if r.strip()}
    results, not_checked, loads, renders = [], [], {}, set()
    counts = Counter({s: 0 for s in SEVERITIES})
    for path in a.inputs:
        data = load(path)
        source, msgs, skipped = extract(data, node_ids)
        not_checked += [dict(s, source=source, parent_id=data.get("_id")) for s in skipped]
        for m in msgs:
            findings, to_load, need_render, stats = check_message(m, regions, a.brand, message_hosts(m))
            key = " / ".join(str(x) for x in (m["name"] or m["id"], m.get("variant"), m.get("language")) if x)
            for l in to_load:
                e = loads.setdefault(l["url"], {"url": l["url"], "primary": False, "messages": []})
                e["primary"] = e["primary"] or l["primary"]
                if key not in e["messages"]:
                    e["messages"].append(key)
            renders.update(need_render)
            counts.update(f["severity"] for f in findings)
            results.append({"message": key, "source": m["source"], "id": m["id"], "parent_id": m.get("parent_id"),
                            "channel": m["channel"],
                            "variant": m.get("variant"), "language": m.get("language"),
                            "counts": {s: sum(f["severity"] == s for f in findings) for s in SEVERITIES},
                            "findings": findings, "stats": stats})
    out = {"ok": True, "messages": results, "not_checked": not_checked,
           "links_to_load": sorted(loads.values(), key=lambda e: (not e["primary"], e["url"])),
           "links_needing_render": sorted(renders), "counts": dict(counts),
           "verdict_before_link_checks": verdict(counts)}
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
