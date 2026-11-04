#!/usr/bin/env python3
"""Turn one Loomi Connect tool problem into a submit_llm_feedback report, lint it, and check the tool's response.

Usage:
  python3 tool_feedback_report.py list-known --doc known-tool-behaviour.md [--published-tools published-tools.txt]
         [--sent-log sent.jsonl] [--out known.json]
  python3 tool_feedback_report.py build --report report.json --environment production|staging
         --private-terms terms.txt [--known-doc known-tool-behaviour.md] [--published-tools published-tools.txt]
         [--sent-log sent.jsonl] [--out plan.json]
  python3 tool_feedback_report.py verify --plan plan.json --response 1=response.json [--sent-log sent.jsonl]
         [--out result.json]

list-known: lists the items in docs/known-tool-behaviour.md marked as worth reporting (references/rules.json
known_marker), with line number, section, the tools they name, a link to the line, and whether the sent log already
has them.

build: --report is ONE report (references/feedback-fields.md). Every string is NFKC-normalised and stripped of
invisible format characters first. client and model are never sent (the tool detects them). Arguments go through an
allow-list: only numbers, booleans, ISO dates and plain values of enum-like keys (allowed_arg_keys) are kept; every
other value becomes a <placeholder> named after its key. A response excerpt that parses as JSON is treated the same
way. Free text, and the quoted known-behaviour line, are redacted (best effort). Then the FINAL strings exactly as
sent are linted: a hard leak (email, URL or host, secret or token, cookie, ID, IP address, card number, IBAN, phone
number, private term) blocks the plan; a soft one (capitalised word pairs, capitalised words in quotes, a name after
"user" or "by", tokens with several _ or - parts, unusual enum values, money, business figures, dotted names) is a
warning, shown masked in the confirmation. The plan carries payload_preview: every field exactly as it will be sent,
for the user to read in full. It has the shape in docs/skill-authoring.md ("Plan files for write skills"): one
create change for submit_llm_feedback, live_impact none.

verify: --response 1=FILE is submit_llm_feedback's saved response. Loomi Connect has no tool to read a report back,
so this reads the response only: accepted (success true or an ID, and no negative wording), rejected (nothing was
recorded: invalid, rate-limited or refused) or unknown (it may have been recorded: never resend). --sent-log appends
accepted and unknown reports, so build blocks sending the same report twice.

It never calls Loomi Connect: the assistant makes the one call, after confirmation. Standard library only.
"""
import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
TOOL_NAME = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
TOOL_VERBS = ("get_", "list_", "search_", "create_", "update_", "delete_", "upsert_", "import_", "clone_", "start_",
              "end_", "archive_", "bulk_", "calculate_", "estimate_", "execute_", "generate_", "preview_", "compare_",
              "validate_", "submit_")


def words(key):
    return "|".join(sorted((re.escape(w) for w in RULES[key]), key=len, reverse=True))


L = r"[^\W\d_]"  # any Unicode letter
STOP = r"[\s<>\"'`)\]}]"
ALLOWED_URL = re.compile(r"^%s(?:#L\d+)?$" % re.escape(RULES["repo_doc_url"]))
URL = re.compile(r"(?:https?|ftp)://[^\s<>\"'`)\]}]+", re.I)
MD_LINK = re.compile(r"\[([^\]\n]*)\]\(([^)\s]+)\)")
PROTOCOL_RELATIVE = re.compile(r"(?<![:\w/])//[\w-]+(?:\.[\w-]+)+[^\s<>\"'`)\]}]*")
SCHEMELESS = re.compile(r"(?<![\w.@/<-])[\w-]+(?:\.[\w-]+)+/[^\s<>\"'`)\]}]*")  # host/path, as in algorithm_fix_plan.py
HOST = re.compile(r"(?<![\w.@/<-])[a-z0-9-]+(?:\.[a-z0-9-]+)+(?![\w-])", re.I)
WWW = re.compile(r"\bwww\d?\.", re.I)
EMAIL = re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}")
OBFUSCATED_EMAIL = re.compile(r"[\w.+-]+\s*(?:\(at\)|\[at\]|\s+at\s+)\s*[\w-]+\s*(?:\(dot\)|\[dot\]|\s+dot\s+)\s*\w+", re.I)
ANY_AT = re.compile(r"@|\(at\)|\[at\]|\s+at\s+\w+\s+dot\s+\w", re.I)
JWT = re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]*")
AUTH_SCHEME = re.compile(r"\b(Bearer|Basic|Digest)\s+(?!<)[^\s,;\"']+", re.I)
TOKEN = re.compile(r"(?<![\w<])(?:%s)" % "|".join(RULES["token_patterns"]))
COOKIE = re.compile(r"\b((?:Set-)?Cookie)\s*:\s*(?!<cookie>)[^\n]+", re.I)
ENCODED = re.compile(r"\S*%3[Dd]\S*")
PAIR = re.compile(r"(?<![\w<-])([\"']?)([A-Za-z_][\w-]{0,60})\1\s*(==|!=|<=|>=|[:=]|\s(?:in|like)\s)\s*"
                  r"(\"[^\"\n]*\"|'[^'\n]*'|[^\s&\"',;)}\]<>\[{]+)", re.I)
SECRET_WS = re.compile(r"(?<![\w<-])((?:[A-Za-z_][\w-]{0,40}?)?(?:key|token|secret|password))\s+(?!<)"
                       r"(?=[^\s]*\d|[^\s]{12,})([^\s&\"',;)}\]<>\[{]+)", re.I)
CONTEXT_ANY = re.compile(r"\b(%s)s?\b(\s*[:=#]?\s*)(?!<)([\w.-]+)" % words("context_any_words"), re.I)
CONTEXT_ID = re.compile(r"\b(%s)s?\b(\s*[:=#]?\s*)(?!<)((?=[\w.-]*\d)[\w.-]+|[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)+)"
                        % words("context_id_words"), re.I)
PERSON = re.compile(r"\b(%s)\b([\"']?\s*[:=]?\s*[\"']?\s*)(%s[^\W\d_'’-]*[’'-]?%s*(?:\s+%s[^\W\d_'’-]*){0,2})"
                    % (words("person_context_words"), L, L, L), re.I)
UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
HEX = re.compile(r"\b(?=[0-9a-fA-F]*[0-9])(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{%d,}\b" % RULES["min_hex_id_chars"])
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
IPV6 = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")
CARD = re.compile(r"(?<![\d])\d(?:[\s/,.-]?\d){12,18}(?!\d)")
PHONE = re.compile(r"(?<![\w<.])\+?\(?\d[\d\s().-]{4,}\d(?![\w>])")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
NUMERIC_ID = re.compile(r"(?<![\w<])\d{%d,}(?![\w>])" % RULES["min_numeric_id_digits"])
DIGITS = re.compile(r"\d{%d,}" % RULES["min_numeric_id_digits"])
OPAQUE = re.compile(r"(?<![\w<])(?=[\w/+=-]*\d)(?=[\w/+=-]*[A-Za-z])[\w/+=-]{%d,}" % RULES["min_opaque_token_chars"])
QUERY_STRING = re.compile(r"\?[\w%.\[\]-]+=")
WORD = re.compile(r"%s[^\W\d_'’-]*(?:['’-]%s+)*" % (L, L))
CURRENCY = words("currency_codes")
MONEY = re.compile(r"[$€£¥₹]\s?\d|\d[\d.,]*\s?[$€£¥₹]|\b(?:%s)\s?\d|\d[\d.,]*\s?(?:%s)\b|\b\d{1,3}(?:,\d{3})+\b"
                   % (CURRENCY, CURRENCY))
METRIC = re.compile(r"\b(?:%s)\b[^\n.;]{0,30}?\d" % words("business_metric_words"), re.I)
PLAIN_VALUE = re.compile(RULES["plain_value_pattern"])
CONTEXT_STOP = {w.lower() for w in RULES["context_stopwords"]}
COMMON_CAPS = {w.lower() for w in RULES["common_capitalised_words"]}
SEPARATED = re.compile(r"(?<![\w<.-])(?=[\w-]*[A-Za-z])[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+){2,}(?![\w>-])")
QUOTED = re.compile(r"'([^'\n]{1,120})'|\"([^\"\n]{1,120})\"")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$")
KEY_OK = re.compile(r"^[a-z][a-z0-9_]*$|^[a-z]+(?:[A-Z][a-z0-9]*)*$")

CONTEXT_ERROR = re.compile(r"\bproject\b|organi[sz]ation|\baccount\b|workspace|permission|\baccess\b|denied|"
                           r"forbidden|unauthori[sz]ed|\b40[13]\b", re.I)
RATE_ERROR = re.compile(r"\b429\b|rate.?limit|too many", re.I)
INVALID_ERROR = re.compile(r"\b40[09]\b|\b422\b|validation|invalid|required|must be|too long|max.?length|"
                           r"exceeds|not one of|enum", re.I)
NEGATIVE = re.compile(r"\b(?:not|never|unable|cannot|can't|couldn't|could not|failed|failure|error|rejected|"
                      r"denied)\b", re.I)
ID_KEYS = ("feedback_id", "submission_id", "id", "_id")


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


def write_out(path, text):
    if path:
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
        except OSError as e:
            fail(f"{path}: can't write it ({e}).")


def norm(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def clean_str(s):
    """NFKC-normalise (full-width @ becomes @) and drop invisible format characters (zero-width, bidi controls)."""
    s = unicodedata.normalize("NFKC", str(s))
    return "".join(c for c in s if unicodedata.category(c) != "Cf")


def clean_deep(v):
    if isinstance(v, dict):
        return {clean_str(k): clean_deep(x) for k, x in v.items()}
    if isinstance(v, list):
        return [clean_deep(x) for x in v]
    if isinstance(v, str):
        return clean_str(v)
    return v


def published_tools(path):
    if not path:
        return None
    names = set()
    for line in read_text(path).splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.add(line.split("\t")[0].split()[0])
    return names


def private_terms(path):
    """(terms, none_used): the names in the file, and whether it says no names were used."""
    terms, none_used = set(), False
    for line in read_text(path).splitlines():
        t = clean_str(line).strip()
        if norm(t) == norm(RULES["private_terms_none_line"]):
            none_used = True
        elif t and not t.startswith("#"):
            terms.add(t)
    return sorted(terms, key=lambda t: (-len(t), t.lower())), none_used


def term_patterns(terms):
    """Each term as a pattern that also matches its variants: case, and spaces, _, . or - between its parts."""
    out = []
    for t in terms:
        parts = [p for p in re.split(r"[\W_]+", t) if p]
        if parts:
            out.append((t, re.compile(r"[\s_.\-]*".join(re.escape(p) for p in parts), re.I)))
    return out


def read_sent_log(path):
    entries = []
    if path and Path(path).exists():
        for i, line in enumerate(read_text(path).splitlines(), 1):
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    fail(f"{path}: line {i} isn't JSON. Use the file that verify --sent-log writes.")
    return entries


def allowed_url(url):
    return bool(ALLOWED_URL.match(url))


# ---------- redaction ----------

def nk(key):
    """A name normalised for every check: lower case, without _, - or spaces (accountId and account_id match)."""
    return re.sub(r"[\s_-]", "", str(key).lower())


def sensitive(key):
    k = nk(key)
    return (k in RULES["sensitive_names_exact"] or any(w in k for w in RULES["sensitive_name_words"])
            or any(k.endswith(s) for s in RULES["sensitive_name_suffixes"]))


def placeholder(key):
    k = re.sub(r"[^a-z0-9]", "", nk(key)) if key is not None else ""
    return f"<{k or 'value'}>"


def _pair(m):
    q, name, sep, value = m.group(1), m.group(2), m.group(3), m.group(4)
    bare = value.strip("\"'")
    if not (sensitive(name) or name.startswith("_")) or bare.startswith("<") or bare.lower() in ("", "null", "none", "true", "false"):
        return m.group(0)
    if nk(name) in RULES["allowed_arg_keys"] and PLAIN_VALUE.match(bare) and not DIGITS.search(bare):
        return m.group(0)
    quote = value[0] if value[:1] in ("\"", "'") and value[-1:] == value[:1] and len(value) > 1 else ""
    sep_out = sep if sep.strip() not in (":",) else ": "
    return f"{q}{name}{q}{sep_out}{quote}{placeholder(name)}{quote}"


def _phone(m):
    s = m.group(0)
    digits = sum(c.isdigit() for c in s)
    if DATE.search(s) or digits < RULES["min_phone_digits"]:
        return s
    if not (s.lstrip("(").startswith("+") or re.search(r"\d[\s().-]+\d", s)):
        return s
    return "<phone>"


def luhn(digits):
    total, alt = 0, False
    for c in reversed(digits):
        d = int(c)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def _card(m):
    s = m.group(0)
    digits = re.sub(r"\D", "", s)
    if DATE.search(s) or not 13 <= len(digits) <= 19 or not luhn(digits):
        return s
    return "<card>"


def host_kind(text):
    """'hard' for a host name, 'soft' for a dotted name that may be one, None for a file name or version."""
    last = text.rsplit(".", 1)[-1].lower()
    if not last.isalpha() or len(last) < 2 or last in RULES["not_host_suffixes"]:
        return None
    if last in RULES["host_tlds"] or len(last) == 2 or text.lower().startswith("www"):
        return "hard"
    return "soft"


def _context_any(m):
    """Any number or token right after account, acct, site, project, catalog, view, workspace or domain key."""
    tok = m.group(3).rstrip(".")
    if tok.lower() in CONTEXT_STOP:
        return m.group(0)
    return f"{m.group(1)}{m.group(2)}<{re.sub(r'[^a-z0-9]', '', nk(m.group(1)))}>" + m.group(3)[len(tok):]


def _ipv6(m):
    s = m.group(0)
    return "<ip>" if s.count(":") >= 2 and ("::" in s or re.search(r"[A-Fa-f]", s)) and re.search(r"[0-9A-Fa-f]", s) else s


def _person(m):
    names = m.group(3).split()
    keep = []
    for i, w in enumerate(names):
        if w[:1].isupper():
            keep.append(i)
        else:
            break
    if not keep:
        return m.group(0)
    rest = " ".join(names[len(keep):])
    return f"{m.group(1)}{m.group(2)}<name>" + (f" {rest}" if rest else "")


def redact_text(text, terms=()):
    """Best-effort replacement of personal and secret-shaped things in free text with <placeholders>."""
    s = clean_str(text)
    s = MD_LINK.sub(lambda m: m.group(0) if allowed_url(m.group(2)) else f"[{m.group(1)}](<url>)", s)
    s = URL.sub(lambda m: m.group(0) if allowed_url(m.group(0)) else "<url>", s)
    s = PROTOCOL_RELATIVE.sub("<url>", s)
    s = EMAIL.sub("<email>", s)
    s = OBFUSCATED_EMAIL.sub("<email>", s)
    s = SCHEMELESS.sub("<url>", s)
    s = JWT.sub("<token>", s)
    s = AUTH_SCHEME.sub(lambda m: f"{m.group(1)} <token>", s)
    s = TOKEN.sub("<token>", s)
    s = COOKIE.sub(lambda m: f"{m.group(1)}: <cookie>", s)
    s = ENCODED.sub("<encoded>", s)
    s = PAIR.sub(_pair, s)
    s = SECRET_WS.sub(lambda m: f"{m.group(1)} {placeholder(m.group(1))}", s)
    s = CONTEXT_ANY.sub(_context_any, s)
    s = CONTEXT_ID.sub(lambda m: f"{m.group(1)}{m.group(2)}<{nk(m.group(1))}>", s)
    s = PERSON.sub(_person, s)
    s = HOST.sub(lambda m: "<host>" if host_kind(m.group(0)) == "hard" else m.group(0), s)
    s = UUID.sub("<id>", s)
    s = HEX.sub("<id>", s)
    s = IBAN.sub("<iban>", s)
    s = IPV4.sub("<ip>", s)
    s = IPV6.sub(_ipv6, s)
    s = CARD.sub(_card, s)
    s = PHONE.sub(_phone, s)
    s = NUMERIC_ID.sub("<id>", s)
    for _, rx in terms:
        s = rx.sub("<name>", s)
    return s


def map_like(parent, obj):
    p = nk(parent) if parent is not None else ""
    if parent is None:
        return False  # the top level of arguments or an excerpt: tool parameter and response field names
    return (p in RULES["map_parent_keys"] or any(p.startswith(x) for x in RULES["map_parent_prefixes"])
            or len(obj) > RULES["max_object_keys"])


def redact_value(value, terms=(), key=None, text_keys=()):
    """Allow-list redaction for arguments and JSON excerpts: keep numbers, booleans, ISO dates and plain values of
    allowed_arg_keys; replace every other string with a placeholder named after its key. Strings under text_keys get
    free-text redaction instead. Keys are kept only when they look like field names (snake_case or lower camelCase)
    and the object isn't map-like (facets, queries, top..., or more than max_object_keys keys)."""
    if isinstance(value, dict):
        out, n = {}, 0
        replace_all = map_like(key, value)
        for k, v in sorted(value.items(), key=lambda kv: str(kv[0])):
            k = str(k)
            if replace_all or not KEY_OK.match(k) or any(rx.search(k) for _, rx in terms):
                n += 1
                k = f"<key{n}>"
            out[k] = redact_value(v, terms, k, text_keys)
        return out
    if isinstance(value, list):
        return [redact_value(v, terms, key, text_keys) for v in value]
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if (key is not None and sensitive(key)) or len(str(abs(int(value)))) >= RULES["min_numeric_id_digits"]:
            return placeholder(key)
        return value
    s = str(value)
    if key is not None and nk(key) in text_keys:
        return redact_text(s, terms)
    if ISO_DATE.match(s) and not (key is not None and sensitive(key)):
        return s
    if (key is not None and nk(key) in RULES["allowed_arg_keys"] and PLAIN_VALUE.match(s)
            and not DIGITS.search(s) and not any(rx.search(s) for _, rx in terms)):
        return s
    return placeholder(key)


def redact_excerpt(text, terms):
    """A JSON excerpt goes through the allow-list (error and message text kept, redacted); anything else is free text."""
    try:
        data = json.loads(text)
    except ValueError:
        return redact_text(text, terms).strip()
    if isinstance(data, str):
        return redact_text(data, terms).strip()
    return json.dumps(redact_value(data, terms, None, {nk(k) for k in RULES["excerpt_text_keys"]}),
                      ensure_ascii=False, sort_keys=True)


# ---------- lint (on the final strings, exactly as sent) ----------

def mask(s):
    s = str(s)
    return f"{s[:1]}... ({len(s)} characters)"


HARD = (
    ("url", URL, "a URL (its host or query string can identify the customer)"),
    ("url", PROTOCOL_RELATIVE, "a //host URL"),
    ("url", SCHEMELESS, "a host with a path"),
    ("url", QUERY_STRING, "a query string"),
    ("host", WWW, "a www. host"),
    ("email", ANY_AT, "an @ or an 'at ... dot' address"),
    ("secret", JWT, "a JWT"),
    ("secret", AUTH_SCHEME, "a Bearer, Basic or Digest credential"),
    ("secret", TOKEN, "a known token format"),
    ("secret", ENCODED, "a %3D-encoded value (cookie or signed parameter)"),
    ("secret", OPAQUE, "a long token or ID"),
    ("cookie", re.compile(r"\b(?:set-)?cookie\s*:\s*(?!<cookie>)\S", re.I), "a cookie header"),
    ("id", UUID, "a UUID-shaped ID"),
    ("id", HEX, "a long hex ID"),
    ("id", DIGITS, "a long number that may be an ID"),
    ("iban", IBAN, "an IBAN"),
    ("ip", IPV4, "an IPv4 address"),
)
REDUCED = ("url", "email", "secret")  # for short fields whose IDs legitimately hold digits and dates


def known_phrase_mask(t):
    for p in sorted(RULES["known_phrases"], key=len, reverse=True):
        t = re.sub(re.escape(p), lambda m: "#" * len(m.group(0)), t)
    return t


def capitalised_pairs(t):
    """Two or more adjacent capitalised words anywhere, sentence start included (a possible person or brand),
    unless they're a known phrase or every word is a common word."""
    t = known_phrase_mask(t)
    groups, cur = [], []
    for m in WORD.finditer(t):
        w = m.group(0)
        if w[:1].isupper() and (len(w) == 1 or not w.isupper()):
            if cur and re.fullmatch(r"[ \t]+", t[cur[-1][1]:m.start()]):
                cur.append((m.start(), m.end()))
                continue
            if cur:
                groups.append(cur)
            cur = [(m.start(), m.end())]
        elif cur:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    found = []
    for g in groups:
        if len(g) >= 2 and not all(t[a:b].lower() in COMMON_CAPS for a, b in g):
            found.append((g[0][0], t[g[0][0]:g[-1][1]]))
    return found


def quoted_capitals(t):
    """Capitalised words inside a quoted string (segment, campaign or customer names in error text)."""
    t = known_phrase_mask(t)
    out = []
    for m in QUOTED.finditer(t):
        inner = m.group(1) if m.group(1) is not None else m.group(2)
        start = m.start() + 1
        for w in WORD.finditer(inner):
            word = w.group(0)
            if word[:1].isupper() and word.lower() not in COMMON_CAPS:
                out.append((start, inner))
                break
    return out


def separated_tokens(t, tools):
    """Tokens with two or more _ or - separators that aren't tool or known field names (domain keys, account ids)."""
    t = known_phrase_mask(t)
    known = {nk(x) for x in RULES["known_field_names"]} | {nk(x) for x in RULES["allowed_arg_keys"]}
    out = []
    for m in SEPARATED.finditer(t):
        tok = m.group(0)
        if tools is not None and tok in tools:
            continue
        if tools is None and TOOL_NAME.match(tok) and tok.startswith(TOOL_VERBS):
            continue
        if nk(tok) in known or tok.lower() in {w.lower() for w in RULES["known_phrases"]}:
            continue
        out.append((m.start(), tok))
    return out


def lint_text(field, text, terms, reduced=False, tools=None):
    """(hard, soft): what's left in one final string. Hard leaks block; soft ones are warnings."""
    t = clean_str(text or "")
    t = URL.sub(lambda m: " " * len(m.group(0)) if allowed_url(m.group(0)) else m.group(0), t)
    hard, soft = [], []

    def line_of(pos):
        return t.count("\n", 0, pos) + 1

    def add(bucket, check, what, m_start, found):
        bucket.append((check, what, line_of(m_start), found))

    for check, rx, what in HARD:
        if reduced and check not in REDUCED:
            continue
        for m in rx.finditer(t):
            if check == "url" and rx is URL and allowed_url(m.group(0)):
                continue
            if rx is DIGITS and (IPV4.search(t[max(0, m.start() - 4):m.end() + 4]) or reduced):
                continue
            add(hard, check, what, m.start(), m.group(0))
    for _, rx in terms:
        for m in rx.finditer(t):
            add(hard, "private_term", "a private name (organisation, project, account, catalog, site, customer or "
                "brand)", m.start(), m.group(0))
    if not reduced:
        for m in MD_LINK.finditer(t):
            if not allowed_url(m.group(2)) and not m.group(2).startswith("<"):
                add(hard, "url", "a link target", m.start(), m.group(2))
        for m in HOST.finditer(t):
            kind = host_kind(m.group(0))
            if kind == "hard":
                add(hard, "host", "a host name", m.start(), m.group(0))
            elif kind == "soft":
                add(soft, "dotted_name", "a dotted name that may be a host", m.start(), m.group(0))
        for m in PAIR.finditer(t):
            if _pair(m) != m.group(0):
                add(hard, "secret", "a sensitive name: value or name=value pair", m.start(), m.group(0))
        for m in SECRET_WS.finditer(t):
            add(hard, "secret", "a value after a key, token, secret or password", m.start(), m.group(0))
        for m in CONTEXT_ID.finditer(t):
            add(hard, "id", "an ID or name after an account, project or similar word", m.start(), m.group(0))
        for m in CONTEXT_ANY.finditer(t):
            if _context_any(m) != m.group(0):
                add(hard, "id", "a number or name after an account, site, catalog or similar word", m.start(),
                    m.group(0))
        for m in IPV6.finditer(t):
            if _ipv6(m) != m.group(0):
                add(hard, "ip", "an IPv6 address", m.start(), m.group(0))
        for m in CARD.finditer(t):
            if _card(m) != m.group(0):
                add(hard, "card", "a card number", m.start(), m.group(0))
        for m in PHONE.finditer(t):
            if _phone(m) != m.group(0):
                add(hard, "phone", "a phone number", m.start(), m.group(0))
        stop = {w.lower() for w in RULES["name_stopwords"]}
        for m in PERSON.finditer(t):
            first = m.group(3).split()[0]
            if first.lower() not in stop:
                add(soft, "person", f"a word after '{m.group(1).lower()}' that may be a name", m.start(3), m.group(3))
        for pos, pair in capitalised_pairs(t):
            add(soft, "capitalised", "capitalised words that may be a person, customer or brand", pos, pair)
        for pos, inner in quoted_capitals(t):
            add(soft, "quoted_name", "capitalised words in a quoted string that may be a name", pos, inner)
        for pos, tok in separated_tokens(t, tools):
            add(soft, "separated_token", "a token with several _ or - parts that may be a domain key or account "
                "name", pos, tok)
        for m in MONEY.finditer(t):
            add(soft, "money", "a money amount or large figure", m.start(), m.group(0))
        for m in METRIC.finditer(t):
            add(soft, "business_figure", "a business figure", m.start(), m.group(0))

    def pack(items):
        out, seen = [], set()
        for check, what, line, found in items:
            k = (check, line, found)
            if k not in seen:
                seen.add(k)
                out.append({"check": check, "field": field, "line": line,
                            "message": f"{field} line {line} contains {what}.", "found": mask(found)})
        return out
    return pack(hard), pack(soft)


# ---------- known-tool-behaviour.md ----------

def known_items(doc_path, tools=None):
    lines = read_text(doc_path).splitlines()
    marker = RULES["known_marker"]
    items = []
    section = subsection = sub_line = None
    for i, line in enumerate(lines, 1):
        if line.startswith("## "):
            section, subsection, sub_line = line[3:].strip(), None, None
            continue
        m = re.match(r"^\*\*(.+?)\*\*", line)
        if m and not line.lstrip().startswith("-"):
            subsection, sub_line = m.group(1).strip(), line
        if marker in line and line.lstrip().startswith("-"):
            items.append(known_item(lines, i, section, subsection, sub_line, tools))
    return items


def bullet_indent(line):
    m = re.match(r"^(\s*)- ", line)
    return len(m.group(1)) if m else None


def tools_named(text, tools):
    found = set()
    for tok in re.findall(r"`([^`]+)`", text):
        tok = tok.strip()
        if TOOL_NAME.match(tok) and (tok in tools if tools is not None else tok.startswith(TOOL_VERBS)):
            found.add(tok)
    return sorted(found)


def known_item(lines, n, section, subsection, sub_line, tools):
    line = lines[n - 1]
    parent = None
    ind = bullet_indent(line)
    if ind:
        for j in range(n - 2, -1, -1):
            pi = bullet_indent(lines[j])
            if pi is not None and pi < ind:
                parent = lines[j].strip()
                break
            if lines[j].startswith("#"):
                break
    cap = RULES["known_excerpt_chars"]
    text = clean_str(line).strip()
    parent = clean_str(parent) if parent else parent
    named = tools_named(text + " " + (parent or ""), tools) or tools_named(sub_line or "", tools)
    return {"line": n, "section": section, "subsection": subsection, "tools": named,
            "text": text[:cap] + ("..." if len(text) > cap else ""),
            "parent": (parent[:cap] + ("..." if len(parent) > cap else "")) if parent else None,
            "link": f"{RULES['repo_doc_url']}#L{n}"}


def find_known(doc_path, n, tools):
    lines = read_text(doc_path).splitlines()
    if not (1 <= n <= len(lines)):
        return None, f"known_line {n} is outside {doc_path} ({len(lines)} lines)."
    if RULES["known_marker"] not in lines[n - 1]:
        return None, (f"line {n} of {doc_path} isn't marked {RULES['known_marker']}. Run list-known and use one of "
                      "its line numbers (the file may have changed).")
    for item in known_items(doc_path, tools):
        if item["line"] == n:
            return item, None
    return None, f"line {n} of {doc_path} isn't a list item."


def cmd_list_known(a):
    tools = published_tools(a.published_tools)
    items = known_items(a.doc, tools)
    sent = read_sent_log(a.sent_log)
    sent_lines = {e.get("known_line") for e in sent if e.get("state") in ("accepted", "unknown")}
    for it in items:
        it["already_sent"] = it["line"] in sent_lines
    return {"ok": True, "doc": Path(a.doc).name, "count": len(items), "items": items,
            "next": "Ask the user to pick ONE item. Report it with build; never send the whole list."}


# ---------- build ----------

def fingerprint(tool, summary):
    return hashlib.sha256(f"{tool}\n{norm(summary)}".encode("utf-8")).hexdigest()[:16]


def one_line(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def unknown_enum_parts(key, value):
    """Parts of a kept enum-like argument value that may be data: underscore-joined words not in known_arg_values,
    or, for a field list (fl), any field not in the list."""
    if not isinstance(value, str) or value.startswith("<") or nk(key) not in RULES["allowed_arg_keys"]:
        return []
    known = {v.lower() for v in RULES["known_arg_values"].get(nk(key), [])}
    is_list = nk(key) in RULES["field_list_keys"]
    return [p for p in re.split(r"[ ,]+", value)
            if p and p.lower() not in known and (is_list or "_" in p)]


def payload_preview(payload):
    """Every field exactly as it will be sent, for the user to read in full before saying yes."""
    lines = [f"gap_type: {payload.get('gap_type')}",
             f"completion_estimate: {payload.get('completion_estimate')}",
             "client: (never sent; the tool detects it)",
             "model: (never sent; the tool detects it)",
             "----- feedback -----", payload.get("feedback", ""),
             "----- what_i_tried -----", payload.get("what_i_tried", "")]
    return "\n".join(lines)


def cmd_build(a):
    rep = raw_json(a.report)
    if isinstance(rep, list):
        fail(f"{a.report}: holds a list. One report per plan: write ONE report object and ask about it on its own.")
    if not isinstance(rep, dict):
        fail(f"{a.report}: expected one JSON object (references/feedback-fields.md).")
    rep = clean_deep(rep)
    term_list, none_used = private_terms(a.private_terms)
    terms = term_patterns(term_list)
    tools = published_tools(a.published_tools)
    problems, warnings = [], []

    def block(check, message, field=None):
        problems.append({"check": check, "field": field, "message": message})

    def warn(check, message, field=None):
        warnings.append({"check": check, "field": field, "message": message})

    if not term_list and not none_used:
        block("private_terms", "The private terms file is empty. List the organisation, project, account, catalog and "
              f"site names used in this session, or, if none were used, a line '{RULES['private_terms_none_line']}'.",
              "private_terms")
    redacted = []

    def clean(field, value):
        out = redact_text(value, terms).strip() if value else ""
        if out != clean_str(value or "").strip():
            redacted.append(field)
        return out

    tool = str(rep.get("tool") or "").strip()
    if not TOOL_NAME.match(tool):
        block("tool", "tool must be one Loomi Connect tool name, such as get_discovery_trend.", "tool")
    elif tools is not None and tool not in tools:
        block("tool", f"{tool} isn't in the published tools list. Check the name (renamed tools fail under their old "
              "name); never report on a tool tagged internal.", "tool")
    if any(rx.search(tool) for _, rx in terms):
        block("private_term", "tool contains a private name.", "tool")

    summary = clean("summary", str(rep.get("summary") or "").strip())
    if not summary:
        block("summary", "summary is empty: write one line saying what goes wrong.", "summary")
    elif "\n" in summary or len(summary) > RULES["summary_max_chars"]:
        block("summary", "summary must be one line of at most summary_max_chars (references/rules.json).", "summary")

    gap = str(rep.get("gap_type") or "").strip().upper()
    if gap not in RULES["gap_types"]:
        block("gap_type", f"gap_type must be one of {', '.join(RULES['gap_types'])}.", "gap_type")

    ce = rep.get("completion_estimate")
    if isinstance(ce, bool) or not isinstance(ce, int) or not RULES["completion_estimate_min"] <= ce <= RULES["completion_estimate_max"]:
        block("completion_estimate", "completion_estimate must be a whole number in the range in references/rules.json "
              "(how close the user got to what they asked for).", "completion_estimate")
        ce = None
    elif ce == RULES["completion_estimate_max"]:
        warn("completion_estimate", "The top completion_estimate means the request was fully done. Is this really a "
             "problem worth reporting?", "completion_estimate")

    product = str(rep.get("product") or "").strip().lower() or None
    if product and product not in RULES["products"]:
        block("product", f"product must be one of {', '.join(RULES['products'])}.", "product")
    if a.environment == "staging" and product == "engagement":
        warn("environment", "Engagement has no staging environment; check --environment.", "environment")

    expected = clean("expected", str(rep.get("expected") or "").strip())
    actual = clean("actual", str(rep.get("actual") or "").strip())
    for name, val in (("expected", expected), ("actual", actual)):
        if not val:
            block(name, f"{name} is empty: say what you expected and what came back.", name)

    args = rep.get("arguments")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        block("arguments", "arguments must be the JSON object sent to the tool ({} if none).", "arguments")
        args = {}
    clean_args = redact_value(args, terms)
    for k, v in sorted(clean_args.items()):
        for part in unknown_enum_parts(k, v):
            warnings.append({"check": "argument_value", "field": "arguments", "line": None, "soft": True,
                             "message": f"arguments: {k} has a value that isn't a common one and may be a name.",
                             "found": mask(part)})
    if clean_args != args:
        redacted.append("arguments")
    raw_excerpt = str(rep.get("response_excerpt") or "").strip()
    excerpt = redact_excerpt(raw_excerpt, terms) if raw_excerpt else ""
    if excerpt and excerpt != raw_excerpt:
        redacted.append("response_excerpt")

    known = None
    if rep.get("known_line") is not None:
        kl = rep.get("known_line")
        if isinstance(kl, bool) or not isinstance(kl, int):
            block("known_line", "known_line must be a line number from list-known.", "known_line")
        elif not a.known_doc:
            block("known_line", "known_line is set, so pass --known-doc with the path of known-tool-behaviour.md.",
                  "known_line")
        else:
            known, err = find_known(a.known_doc, kl, tools)
            if err:
                block("known_line", err, "known_line")
            elif tool and tool not in known["tools"] and known["tools"]:
                warn("known_line", f"Line {kl} names {', '.join(known['tools'])}, not {tool}. Check the line.",
                     "known_line")

    for name in ("client", "model"):
        if rep.get(name):
            warn("client_model_ignored", f"{name} is ignored and never sent: the tool detects it itself, and free "
                 "text there could leak a name.", name)

    what = clean("what_i_tried", str(rep.get("what_i_tried") or "").strip()) or (
        f"Called {tool} with the arguments in the reproduction below the feedback, and compared what came back "
        "with the tool's description.")
    suggestion = clean("suggestion", str(rep.get("suggestion") or "").strip())

    env_bits = [f"Product: {product}" if product else None, f"Environment: {a.environment}"]
    parts = [f"{RULES['report_prefix']} {tool}: {one_line(summary)}", "",
             " | ".join(b for b in env_bits if b), "", f"Expected: {expected}", f"Actual: {actual}", "",
             "Minimal reproduction (IDs, names, emails, URLs and secrets replaced with placeholders):",
             f"  tool: {tool}",
             "  arguments: " + json.dumps(clean_args, ensure_ascii=False, sort_keys=True)]
    if excerpt:
        parts += ["", "Response excerpt (placeholders as above):", excerpt]
    if known:
        where = known["section"] + (f" / {known['subsection']}" if known["subsection"] else "")
        parts += ["", f"Recorded in the Loomi Connect Community repo's known tool behaviour ({where}, line "
                  f"{known['line']}): {known['link']}"]
        if known["parent"]:
            parts.append("> " + redact_text(known["parent"], terms))
        parts.append("> " + redact_text(known["text"], terms))
    if suggestion:
        parts += ["", f"Suggestion: {suggestion}"]
    feedback = "\n".join(parts)

    payload = {"gap_type": gap, "what_i_tried": what, "feedback": feedback}
    if ce is not None:
        payload["completion_estimate"] = ce

    for name, val in (("feedback", feedback), ("what_i_tried", what)):
        if len(val) > RULES["max_field_chars"]:
            block("length", f"{name} is {len(val)} characters, over the tool's max_field_chars "
                  "(references/rules.json). Shorten the response excerpt or the text.", name)

    # Lint the final strings exactly as sent: hard leaks block, soft ones are warnings shown in the confirmation.
    for name, val in (("feedback", feedback), ("what_i_tried", what)):
        hard, soft = lint_text(name, val, terms, tools=tools)
        problems.extend(hard)
        warnings.extend(dict(w, soft=True) for w in soft)
    if redacted:
        warn("redacted", "Placeholders were put into " + ", ".join(redacted) + ". Check they didn't remove what the "
             "team needs, and read every line: redaction is best effort.", None)

    fp = fingerprint(tool, summary)
    for e in read_sent_log(a.sent_log):
        if e.get("state") not in ("accepted", "unknown"):
            continue
        same_known = known is not None and e.get("known_line") == known["line"]
        if e.get("fingerprint") == fp or same_known:
            block("already_sent", "This report was already sent in an earlier run" +
                  (" (or may have been: the response was unclear)" if e.get("state") == "unknown" else "") +
                  ". Don't send it again.", None)
            break

    status = "blocked" if problems else "ready"
    ch = {"n": 1, "status": status, "kind": "create",
          "target": f"one feedback report to the Loomi Connect team about {tool or 'a tool'}",
          "tool": "submit_llm_feedback", "payload": payload, "before": None,
          "after": {"submitted": True, "gap_type": gap, "feedback_sha256": hashlib.sha256(feedback.encode("utf-8")).hexdigest()},
          "undo": [], "undo_note": "A sent report can't be withdrawn or edited through Loomi Connect. If it was wrong, "
          "send a short follow-up report that says so, after a new yes.",
          "live_impact": "none",
          "impact_note": "None: it changes nothing in Bloomreach. It sends text to the Loomi Connect team.",
          "problems": problems, "warnings": warnings}
    summary_out = {"tool": tool, "summary": one_line(summary), "gap_type": gap, "completion_estimate": ce,
                   "product": product, "environment": a.environment, "known_link": known["link"] if known else None,
                   "feedback_chars": len(feedback), "what_i_tried_chars": len(what),
                   "soft_warnings": sum(1 for w in warnings if w.get("soft"))}
    return {"ok": True, "environment": a.environment, "fingerprint": fp,
            "known_line": known["line"] if known else None, "changes": [ch],
            "batches": [[1]] if status == "ready" else [], "summary": summary_out,
            "payload_preview": payload_preview(payload),
            "confirm_note": "Show payload_preview verbatim in a fenced block, list every warning, and ask the user to "
                            "read every line: redaction is best effort.",
            "counts": {"ready": int(status == "ready"), "blocked": int(status == "blocked"), "no_change": 0}}


# ---------- verify ----------

def numbered_file(text):
    """N=FILE, split on the first "=": a plan change number and its response file."""
    n, sep, path = text.partition("=")
    if not sep or not path:
        raise argparse.ArgumentTypeError("use N=FILE, e.g. 1=response.json")
    try:
        return int(n), path
    except ValueError:
        raise argparse.ArgumentTypeError(f"{n!r} isn't a change number")


def find_id(d, depth=0):
    if not isinstance(d, dict) or depth > 2:
        return None
    for k in ID_KEYS:
        if isinstance(d.get(k), (str, int)) and not isinstance(d.get(k), bool) and str(d.get(k)).strip():
            return str(d[k])
    for k in ("result", "data"):
        got = find_id(d.get(k), depth + 1)
        if got:
            return got
    return None


def error_of(d):
    """The error text of a failed response, or None."""
    for x in (d, d.get("result") if isinstance(d, dict) else None):
        if not isinstance(x, dict):
            continue
        if x.get("success") is False or x.get("isError") is True or x.get("is_error") is True:
            return str(x.get("error") or x.get("message") or x.get("detail") or "no error text")
        if x.get("error"):
            return str(x["error"])
    return None


def message_text(d, depth=0):
    """The human-readable text in a response (message, detail, status), to check for negative wording."""
    if not isinstance(d, dict) or depth > 2:
        return ""
    parts = [str(d[k]) for k in ("message", "detail", "status", "note") if isinstance(d.get(k), str)]
    parts += [message_text(d.get(k), depth + 1) for k in ("result", "data")]
    return " ".join(p for p in parts if p)


def classify_error(err):
    if CONTEXT_ERROR.search(err):
        return "rejected", "context", True, ("Loomi Connect refused it for access reasons. Stop: check the connection "
                                             "and the user's access before anything else.")
    if RATE_ERROR.search(err):
        return "rejected", "rate_limited", True, ("Rate-limited, so nothing was recorded. Wait at least the Retry-After "
                                                  f"time (and at least min_seconds_between_reports, "
                                                  f"{RULES['min_seconds_between_reports']} seconds), then ask the user "
                                                  "again before sending.")
    if INVALID_ERROR.search(err):
        return "rejected", "invalid", False, ("The tool rejected the report, so nothing was recorded. Fix the report, "
                                              "run build again and ask the user again.")
    return "unknown", "unclear_error", False, ("The error doesn't say whether the report was recorded. Don't send it "
                                               "again; tell the user it may have been received.")


def read_response(path):
    text = read_text(path)
    try:
        return json.loads(text), text
    except ValueError:
        return None, text


def cmd_verify(a):
    plan = raw_json(a.plan)
    if not isinstance(plan, dict) or not isinstance(plan.get("changes"), list):
        fail(f"{a.plan}: not a plan file (no changes list). Use the file that tool_feedback_report.py build wrote.")
    by_n = {ch.get("n"): ch for ch in plan["changes"] if isinstance(ch, dict)}
    results, log = [], []
    for n, path in sorted(dict(a.response).items()):
        ch = by_n.get(n)
        if ch is None or ch.get("status") != "ready":
            fail(f"--response {n}: the plan has no ready change {n}.")
        data, text = read_response(path)
        res = {"n": n, "tool": ch.get("tool"), "target": ch.get("target")}
        err = error_of(data) if data is not None else (text if NEGATIVE.search(text) else None)
        if err is not None:
            state, reason, stop, note = classify_error(err)
            res.update(state=state, reason=reason, stop=stop, error=redact_text(err)[:200], note=note)
        else:
            fid = find_id(data) if isinstance(data, dict) else None
            success = isinstance(data, dict) and (data.get("success") is True or (
                isinstance(data.get("result"), dict) and data["result"].get("success") is True))
            ok = (success or bool(fid)) and not NEGATIVE.search(message_text(data))
            if ok:
                res.update(state="accepted", feedback_id=fid, note="The tool accepted the report." +
                           ("" if fid else " It returned no ID."))
            else:
                res.update(state="unknown", reason="no_success_signal", stop=False,
                           note="The response neither confirms nor rejects the report. Don't send it again; tell the "
                           "user it may have been received.")
        results.append(res)
        if res["state"] in ("accepted", "unknown"):
            log.append({"fingerprint": plan.get("fingerprint"), "known_line": plan.get("known_line"),
                        "tool": (plan.get("summary") or {}).get("tool"), "state": res["state"],
                        "feedback_id": res.get("feedback_id")})
    if a.sent_log and log:
        try:
            with open(a.sent_log, "a", encoding="utf-8", newline="\n") as f:
                for e in log:
                    f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError as e:
            fail(f"{a.sent_log}: can't write it ({e}).")
    return {"ok": True, "results": results,
            "read_back": "none: Loomi Connect has no published tool to read a sent report back, so this checks the "
                         "submit_llm_feedback response only.",
            "next": "When the Loomi Connect team confirms a fix, update docs/known-tool-behaviour.md by pull request."}


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # reports can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("list-known", help="list the known-behaviour items marked as worth reporting")
    k.add_argument("--doc", required=True, help="path of docs/known-tool-behaviour.md")
    k.add_argument("--published-tools", help="path of docs/published-tools.txt, to pick out tool names exactly")
    k.add_argument("--sent-log", help="the sent log verify writes, to mark items already reported")
    k.add_argument("--out", help="also write the list to this file")
    b = sub.add_parser("build", help="build, redact and lint one report, and write the plan")
    b.add_argument("--report", required=True, help="ONE report as JSON (references/feedback-fields.md)")
    b.add_argument("--environment", required=True, choices=RULES["environments"],
                   help="where the problem happened; required, no default")
    b.add_argument("--known-doc", help="path of docs/known-tool-behaviour.md, needed when the report has known_line")
    b.add_argument("--private-terms", required=True,
                   help="file of private names, one per line: the session's organisation, project, account, catalog "
                        "and site names, and any customer or brand the user flagged")
    b.add_argument("--published-tools", help="path of docs/published-tools.txt, to check the tool name")
    b.add_argument("--sent-log", help="the sent log verify writes, to block sending the same report twice")
    b.add_argument("--out", help="also write the plan to this file")
    v = sub.add_parser("verify", help="read submit_llm_feedback's response (there is no read-back tool)")
    v.add_argument("--plan", required=True, help="the plan file from build")
    v.add_argument("--response", action="append", type=numbered_file, required=True,
                   help="N=FILE: submit_llm_feedback's saved response for change N")
    v.add_argument("--sent-log", help="append accepted and unclear reports to this JSON-lines file")
    v.add_argument("--out", help="also write the result to this file")
    a = ap.parse_args()
    out = {"list-known": cmd_list_known, "build": cmd_build, "verify": cmd_verify}[a.cmd](a)
    text = json.dumps(out, indent=2, ensure_ascii=False)
    write_out(a.out, text)
    print(text)


if __name__ == "__main__":
    main()
