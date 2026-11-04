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

build: --report is ONE report (references/feedback-fields.md): tool, summary, gap_type, completion_estimate, expected,
actual, arguments, and optionally response_excerpt, what_i_tried, suggestion, product, known_line, client, model.
Arguments go through an allow-list: only numbers, booleans, ISO dates and plain values of enum-like keys
(allowed_arg_keys) are kept; every other value becomes a <placeholder> named after its key. A response excerpt that
parses as JSON is treated the same way. Free text is redacted (URLs and hosts, emails, tokens and secret pairs, IDs,
IP addresses, phone numbers, names after "user", "by" and similar, and every --private-terms entry), then linted
with the same patterns and stricter ones: anything left, or a field over the tool's length limit, makes the change
blocked. Redaction is best effort: the assistant and the user still read the whole report before it's sent. It
prints a plan in the shape in docs/skill-authoring.md ("Plan files for write skills"): one create change for
submit_llm_feedback, live_impact none.

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
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
TOOL_NAME = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
TOOL_VERBS = ("get_", "list_", "search_", "create_", "update_", "delete_", "upsert_", "import_", "clone_", "start_",
              "end_", "archive_", "bulk_", "calculate_", "estimate_", "execute_", "generate_", "preview_", "compare_",
              "validate_", "submit_")


def words(key):
    return "|".join(sorted((re.escape(w) for w in RULES[key]), key=len, reverse=True))


# Shared by redaction and lint. A placeholder is <name>; nothing here matches inside one.
URL = re.compile(r"https?://[^\s<>\"'`)\]}]+", re.I)
PROTOCOL_RELATIVE = re.compile(r"(?<![:\w/])//[\w-]+(?:\.[\w-]+)+[^\s<>\"'`)\]}]*")
SCHEMELESS = re.compile(r"(?<![\w.@/<-])[\w-]+(?:\.[\w-]+)+/[^\s<>\"'`)\]}]*")  # host/path, as in algorithm_fix_plan.py
BARE_HOST = re.compile(r"(?<![\w.@/<-])(?:www\d?\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:%s)\b(?![.-]\w)" % words("host_tlds"), re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
JWT = re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]*")
AUTH_SCHEME = re.compile(r"\b(Bearer|Basic)\s+(?!<)[^\s,;\"']+", re.I)
TOKEN = re.compile(r"(?<![\w<])(?:%s)" % "|".join(RULES["token_patterns"]))
PAIR = re.compile(r"(?<![\w<-])([\"']?)([A-Za-z][\w-]{0,60})\1\s*([:=])\s*(\"[^\"\n]*\"|'[^'\n]*'|[^\s&\"',;)}\]<>]+)")
CONTEXT_ID = re.compile(r"\b(%s)s?\b(\s*[:=#]?\s*)(?!<)((?=[\w.-]*\d)[\w.-]+|[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)+)"
                        % words("context_id_words"), re.I)
PERSON = re.compile(r"\b((?i:%s))\b([\"']?\s*[:=]?\s*[\"']?\s*)([A-Z][a-z'À-ſ-]+(?:\s+[A-Z][a-z'À-ſ-]+)+)"
                    % words("person_context_words"))
UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
HEX = re.compile(r"\b(?=[0-9a-fA-F]*[0-9])(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{%d,}\b" % RULES["min_hex_id_chars"])
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
PHONE = re.compile(r"(?<![\w<.])\+?\(?\d[\d\s().-]{4,}\d(?![\w>])")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
NUMERIC_ID = re.compile(r"(?<![\w<])\d{%d,}(?![\w>])" % RULES["min_numeric_id_digits"])
# Lint only: stricter, so a redaction miss still blocks.
LOOSE_EMAIL = re.compile(r"[^\s<@]@[^\s>@]+\.\w")
OPAQUE = re.compile(r"(?<![\w<])(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[\w-]{%d,}" % RULES["min_opaque_token_chars"])
QUERY_STRING = re.compile(r"\?[\w%.\[\]-]+=")
WWW = re.compile(r"\bwww\d?\.", re.I)
DIGITS = re.compile(r"\d{%d,}" % RULES["min_numeric_id_digits"])
PLAIN_VALUE = re.compile(RULES["plain_value_pattern"])
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$")
SAFE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,40}$")

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
    if not path:
        return []
    terms = [t.strip() for t in read_text(path).splitlines()]
    return sorted({t for t in terms if t and not t.startswith("#")}, key=lambda t: (-len(t), t.lower()))


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
    return any(url.startswith(p) for p in RULES["allowed_url_prefixes"]) and "?" not in url


# ---------- redaction ----------

def nk(key):
    """A name normalised for every check: lower case, without _, - or spaces (accountId and account_id match)."""
    return re.sub(r"[\s_-]", "", str(key).lower())


def sensitive(key):
    k = nk(key)
    return k in RULES["sensitive_names_exact"] or any(w in k for w in RULES["sensitive_name_words"]) or any(k.endswith(s) for s in RULES["sensitive_name_suffixes"])


def placeholder(key):
    k = re.sub(r"[^a-z0-9]", "", nk(key)) if key is not None else ""
    return f"<{k or 'value'}>"


def _pair(m):
    q, name, sep, value = m.group(1), m.group(2), m.group(3), m.group(4)
    bare = value.strip("\"'")
    if not sensitive(name) or bare.startswith("<") or bare.lower() in ("", "null", "none", "true", "false"):
        return m.group(0)
    if nk(name) in RULES["allowed_arg_keys"] and PLAIN_VALUE.match(bare) and not DIGITS.search(bare):
        return m.group(0)
    quote = value[0] if value[:1] in ("\"", "'") and value[-1:] == value[:1] and len(value) > 1 else ""
    space = " " if sep == ":" else ""
    return f"{q}{name}{q}{sep}{space}{quote}{placeholder(name)}{quote}"


def _phone(m):
    s = m.group(0)
    digits = sum(c.isdigit() for c in s)
    if DATE.search(s) or digits < RULES["min_phone_digits"]:
        return s
    if not (s.lstrip("(").startswith("+") or re.search(r"\d[\s().-]+\d", s)):
        return s
    return "<phone>"


def redact_text(text, terms=()):
    """Best-effort replacement of personal and secret-shaped things in free text with <placeholders>."""
    s = str(text)
    s = URL.sub(lambda m: m.group(0) if allowed_url(m.group(0)) else "<url>", s)
    s = PROTOCOL_RELATIVE.sub("<url>", s)
    s = EMAIL.sub("<email>", s)
    s = SCHEMELESS.sub("<url>", s)
    s = JWT.sub("<token>", s)
    s = AUTH_SCHEME.sub(lambda m: f"{m.group(1)} <token>", s)
    s = TOKEN.sub("<token>", s)
    s = PAIR.sub(_pair, s)
    s = CONTEXT_ID.sub(lambda m: f"{m.group(1)}{m.group(2)}<{nk(m.group(1))}>", s)
    s = PERSON.sub(lambda m: f"{m.group(1)}{m.group(2)}<name>", s)
    s = BARE_HOST.sub("<host>", s)
    s = UUID.sub("<id>", s)
    s = HEX.sub("<id>", s)
    s = IPV4.sub("<ip>", s)
    s = PHONE.sub(_phone, s)
    s = NUMERIC_ID.sub("<id>", s)
    for t in terms:
        s = re.sub(re.escape(t), "<name>", s, flags=re.I)
    return s


def redact_value(value, terms=(), key=None, text_keys=()):
    """Allow-list redaction for arguments and JSON excerpts: keep numbers, booleans, ISO dates and plain values of
    allowed_arg_keys; replace every other string with a placeholder named after its key. Strings under text_keys get
    free-text redaction instead. Keys that aren't plain names (data used as a key) are replaced too."""
    if isinstance(value, dict):
        out, n = {}, 0
        for k, v in sorted(value.items(), key=lambda kv: str(kv[0])):
            k = str(k)
            if not SAFE_KEY.match(k) or any(t.lower() in k.lower() for t in terms):
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
            and not DIGITS.search(s) and not any(t.lower() in s.lower() for t in terms)):
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


# ---------- lint ----------

def mask(s):
    s = str(s)
    return f"{s[:1]}... ({len(s)} characters)"


LINT = (
    ("url", URL, "a URL (its host or query string can identify the customer); write <url>"),
    ("url", PROTOCOL_RELATIVE, "a //host URL; write <url>"),
    ("url", SCHEMELESS, "a host with a path; write <url>"),
    ("url", QUERY_STRING, "a query string; write <url>"),
    ("host", BARE_HOST, "a host name; write <host>"),
    ("host", WWW, "a www. host; write <host>"),
    ("email", EMAIL, "an email address; write <email>"),
    ("email", LOOSE_EMAIL, "something shaped like an email address; write <email>"),
    ("secret", JWT, "a JWT; write <token>"),
    ("secret", AUTH_SCHEME, "a Bearer or Basic credential; write <token>"),
    ("secret", TOKEN, "a known token format; write <token>"),
    ("id", UUID, "a UUID-shaped ID; write <id> or a named placeholder such as <project_id>"),
    ("id", HEX, "a long hex ID; write <id> or a named placeholder"),
    ("id", DIGITS, "a long number that may be an ID; write <id>"),
    ("id", OPAQUE, "a long token or ID; write <id> or <token>"),
    ("ip", IPV4, "an IP address; write <ip>"),
)


def lint_text(field, text, terms):
    """Every personal or secret-shaped thing left in one field, without repeating it."""
    hits = []
    t = URL.sub(lambda m: " " if allowed_url(m.group(0)) else m.group(0), str(text or ""))
    for check, rx, message in LINT:
        for m in rx.finditer(t):
            if rx is DIGITS and IPV4.search(m.group(0)):
                continue
            hits.append((check, message, m.group(0)))
    for m in PAIR.finditer(t):
        if _pair(m) != m.group(0):
            hits.append(("secret", "a sensitive name: value or name=value pair; write a <placeholder>", m.group(0)))
    for m in CONTEXT_ID.finditer(t):
        hits.append(("id", "an ID or name after an account, project or similar word; write a <placeholder>", m.group(0)))
    for m in PERSON.finditer(t):
        hits.append(("person", "what looks like a person's name; write <name>", m.group(0)))
    for m in PHONE.finditer(t):
        if _phone(m) != m.group(0):
            hits.append(("phone", "a phone number; write <phone>", m.group(0)))
    low = t.lower()
    for term in terms:
        if term.lower() in low:
            hits.append(("private_term", "a private name (organisation, project, account, catalog, site, customer or "
                         "brand); write a placeholder", term))
    out, seen = [], set()
    for check, message, found in hits:
        k = (check, found)
        if k not in seen:
            seen.add(k)
            out.append({"check": check, "field": field, "message": f"{field} contains {message}.", "found": mask(found)})
    return out


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
    text = line.strip()
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


def cmd_build(a):
    rep = raw_json(a.report)
    if isinstance(rep, list):
        fail(f"{a.report}: holds a list. One report per plan: write ONE report object and ask about it on its own.")
    if not isinstance(rep, dict):
        fail(f"{a.report}: expected one JSON object (references/feedback-fields.md).")
    terms = private_terms(a.private_terms)
    tools = published_tools(a.published_tools)
    problems, warnings = [], []

    def block(check, message, field=None):
        problems.append({"check": check, "field": field, "message": message})

    def warn(check, message, field=None):
        warnings.append({"check": check, "field": field, "message": message})

    if not terms:
        warn("private_terms", "The private terms file is empty. It must list the organisation, project, account, "
             "catalog and site names used in this session, and any customer or brand the user flagged.",
             "private_terms")
    redacted = []

    def clean(field, value):
        out = redact_text(value, terms).strip() if value else ""
        if out != (value or "").strip():
            redacted.append(field)
        return out

    tool = str(rep.get("tool") or "").strip()
    if not TOOL_NAME.match(tool):
        block("tool", "tool must be one Loomi Connect tool name, such as get_discovery_trend.", "tool")
    elif tools is not None and tool not in tools:
        warn("tool", f"{tool} isn't in the published tools list. Check the name (renamed tools fail under their old "
             "name); never report on a tool tagged internal.", "tool")

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

    client = str(rep.get("client") or "").strip()
    model = str(rep.get("model") or "").strip()
    for name, val in (("client", client), ("model", model)):
        if len(val) > RULES["max_short_field_chars"]:
            block("length", f"{name} is longer than max_short_field_chars (references/rules.json).", name)

    what = clean("what_i_tried", str(rep.get("what_i_tried") or "").strip()) or (
        f"Called {tool} with the arguments in the reproduction below the feedback, and compared what came back "
        "with the tool's description.")
    suggestion = clean("suggestion", str(rep.get("suggestion") or "").strip())
    if redacted:
        warn("redacted", "Placeholders were put into " + ", ".join(redacted) + ". Read the whole report: redaction is "
             "best effort and can miss names, IDs and business data, or remove something the team needs.", None)

    env_bits = [f"Product: {product}" if product else None, f"Environment: {a.environment}",
                f"Client: {client}" if client else None]
    parts = [f"{RULES['report_prefix']} {tool}: {one_line(summary)}", "",
             " | ".join(b for b in env_bits if b), "", f"Expected: {expected}", f"Actual: {actual}", "",
             "Minimal reproduction (IDs, account and project names, emails, URLs and secrets replaced by placeholders):",
             f"  tool: {tool}",
             "  arguments: " + json.dumps(clean_args, ensure_ascii=False, sort_keys=True)]
    if excerpt:
        parts += ["", "Response excerpt (placeholders as above):", excerpt]
    if known:
        where = known["section"] + (f" / {known['subsection']}" if known["subsection"] else "")
        parts += ["", f"Recorded in the Loomi Connect Community repo's known tool behaviour ({where}, line "
                  f"{known['line']}): {known['link']}"]
        if known["parent"]:
            parts.append("> " + known["parent"])
        parts.append("> " + known["text"])
    if suggestion:
        parts += ["", f"Suggestion: {suggestion}"]
    feedback = "\n".join(parts)

    payload = {"gap_type": gap, "what_i_tried": what, "feedback": feedback}
    if ce is not None:
        payload["completion_estimate"] = ce
    if client:
        payload["client"] = client
    if model:
        payload["model"] = model

    for name, val in (("feedback", feedback), ("what_i_tried", what)):
        if len(val) > RULES["max_field_chars"]:
            block("length", f"{name} is {len(val)} characters, over the tool's max_field_chars "
                  "(references/rules.json). Shorten the response excerpt or the text.", name)

    lint_fields = (("summary", summary), ("expected", expected), ("actual", actual), ("suggestion", suggestion),
                   ("what_i_tried", what), ("arguments", json.dumps(clean_args, ensure_ascii=False)),
                   ("response_excerpt", excerpt), ("client", client), ("model", model))
    for name, val in lint_fields:
        for hit in lint_text(name, val, terms):
            problems.append(hit)

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
                   "feedback_chars": len(feedback), "what_i_tried_chars": len(what)}
    return {"ok": True, "environment": a.environment, "fingerprint": fp,
            "known_line": known["line"] if known else None, "changes": [ch],
            "batches": [[1]] if status == "ready" else [], "summary": summary_out,
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
