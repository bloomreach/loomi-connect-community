#!/usr/bin/env python3
"""Turn one Loomi Connect tool problem into a submit_llm_feedback report, lint it, and check the tool's response.

Usage:
  python3 tool_feedback_report.py list-known --doc known-tool-behaviour.md [--published-tools published-tools.txt]
         [--sent-log sent.jsonl] [--out known.json]
  python3 tool_feedback_report.py build --report report.json --environment production|staging
         [--known-doc known-tool-behaviour.md] [--private-terms terms.txt] [--published-tools published-tools.txt]
         [--sent-log sent.jsonl] [--out plan.json]
  python3 tool_feedback_report.py verify --plan plan.json --response 1=response.json [--sent-log sent.jsonl]
         [--out result.json]

list-known: lists the items in docs/known-tool-behaviour.md marked as worth reporting (references/rules.json
known_marker), with line number, section, the tools they name, a link to the line, and whether the sent log already
has them.

build: --report is ONE report (references/report-format.md): tool, summary, gap_type, completion_estimate, expected,
actual, arguments, and optionally response_excerpt, what_i_tried, suggestion, product, known_line, client, model.
It replaces every ID, account or project name, email, URL, auth_key, token and other secret in the arguments and the
response excerpt with a <placeholder>, writes the feedback text, and lints everything: an email, a secret-shaped
pair, a long hex or UUID ID, a URL outside this repository, a phone number or a --private-terms entry left anywhere,
or a field over the tool's length limit, makes the change blocked. It prints a plan in the shape in
docs/skill-authoring.md ("Plan files for write skills"): one create change for submit_llm_feedback, live_impact none.

verify: --response 1=FILE is submit_llm_feedback's saved response. Loomi Connect has no tool to read a report back,
so this reads the response only: accepted (with the ID when there is one), rejected (nothing was recorded: invalid
or rate-limited) or unknown (it may have been recorded: never resend). --sent-log appends accepted and unknown
reports, so build blocks sending the same report twice.

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
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
URL = re.compile(r"https?://[^\s<>\"'`)\]}]+", re.I)
UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
HEX = re.compile(r"\b(?=[0-9a-fA-F]*[0-9])(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{%d,}\b|\b[0-9]{%d,}\b"
                 % (RULES["min_hex_id_chars"], RULES["min_hex_id_chars"]))
PHONE = re.compile(r"\+\d[\d\s().-]{7,}\d")
BEARER = re.compile(r"\bBearer\s+(?!<)[A-Za-z0-9._~+/=-]{8,}", re.I)
_NAMES = "|".join(sorted((re.escape(n) for n in RULES["secret_names"]), key=len, reverse=True))
SECRET_EQ = re.compile(r"(?<![A-Za-z0-9_])(%s)\s*=\s*(?!<)(?!(?:null|none|true|false)\b)([^\s&\"',;)}\]<>]+)" % _NAMES, re.I)
SECRET_JSON = re.compile(r"([\"'])(%s)\1\s*:\s*([\"'])(?!<)([^\"']+)\3" % _NAMES, re.I)
CONTEXT_ERROR = re.compile(r"\bproject\b|organi[sz]ation|\baccount\b|workspace|permission|\baccess\b|denied|"
                           r"forbidden|unauthori[sz]ed|\b40[13]\b", re.I)
RATE_ERROR = re.compile(r"\b429\b|rate.?limit|too many", re.I)
INVALID_ERROR = re.compile(r"\b40[09]\b|\b422\b|validation|invalid|required|must be|too long|max.?length|"
                           r"exceeds|not one of|enum", re.I)
SUCCESS_WORDS = re.compile(r"\b(success|submitted|received|recorded|thank)", re.I)
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

def key_is_sensitive(key):
    k = str(key).lower()
    return k in RULES["placeholder_keys"] or any(k.endswith(s) for s in RULES["placeholder_key_suffixes"])


def redact_text(text, terms=()):
    """Replace URLs, emails, secret pairs, IDs, phone numbers and flagged names in free text with placeholders."""
    s = str(text)
    s = URL.sub(lambda m: m.group(0) if allowed_url(m.group(0)) else "<url>", s)
    s = EMAIL.sub("<email>", s)
    s = BEARER.sub("Bearer <token>", s)
    s = SECRET_JSON.sub(lambda m: f'{m.group(1)}{m.group(2)}{m.group(1)}: {m.group(3)}<{m.group(2).lower()}>{m.group(3)}', s)
    s = SECRET_EQ.sub(lambda m: f"{m.group(1)}=<{m.group(1).lower()}>", s)
    s = UUID.sub("<id>", s)
    s = HEX.sub("<id>", s)
    s = PHONE.sub("<phone>", s)
    for t in terms:
        s = re.sub(re.escape(t), "<name>", s, flags=re.I)
    return s


def redact_args(value, terms=(), key=None):
    if key is not None and key_is_sensitive(key) and value not in (None, True, False, "", [], {}):
        return f"<{str(key).lower()}>"
    if isinstance(value, dict):
        return {str(k): redact_args(v, terms, k) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, list):
        return [redact_args(v, terms) for v in value]
    if isinstance(value, str):
        return redact_text(value, terms)
    return value


# ---------- lint ----------

def mask(s):
    s = str(s)
    return f"{s[:1]}... ({len(s)} characters)"


def lint_text(field, text, terms):
    """Every personal or secret-shaped thing left in one field, without repeating it."""
    hits = []
    t = str(text or "")
    for m in URL.finditer(t):
        if not allowed_url(m.group(0)):
            hits.append(("url", "a URL (its host or query string can identify the customer); write <url>", m.group(0)))
    for m in EMAIL.finditer(t):
        hits.append(("email", "an email address; write <email>", m.group(0)))
    for rx, what in ((SECRET_EQ, "a secret-shaped name=value pair"), (SECRET_JSON, "a secret-shaped JSON pair"),
                     (BEARER, "a bearer token")):
        for m in rx.finditer(t):
            hits.append(("secret", f"{what}; write a <placeholder>", m.group(0)))
    for m in UUID.finditer(t):
        hits.append(("id", "a UUID-shaped ID; write <id> or a named placeholder such as <project_id>", m.group(0)))
    for m in HEX.finditer(t):
        hits.append(("id", "a long hex or numeric ID; write <id> or a named placeholder", m.group(0)))
    for m in PHONE.finditer(t):
        hits.append(("phone", "a phone number; write <phone>", m.group(0)))
    low = t.lower()
    for term in terms:
        if term.lower() in low:
            hits.append(("private_term", "a name you flagged as private; write a placeholder", term))
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
        fail(f"{a.report}: expected one JSON object (references/report-format.md).")
    terms = private_terms(a.private_terms)
    tools = published_tools(a.published_tools)
    problems, warnings = [], []

    def block(check, message, field=None):
        problems.append({"check": check, "field": field, "message": message})

    def warn(check, message, field=None):
        warnings.append({"check": check, "field": field, "message": message})

    tool = str(rep.get("tool") or "").strip()
    if not TOOL_NAME.match(tool):
        block("tool", "tool must be one Loomi Connect tool name, such as get_discovery_trend.", "tool")
    elif tools is not None and tool not in tools:
        warn("tool", f"{tool} isn't in the published tools list. Check the name (renamed tools fail under their old "
             "name); never report on a tool tagged internal.", "tool")

    summary = str(rep.get("summary") or "").strip()
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

    expected = str(rep.get("expected") or "").strip()
    actual = str(rep.get("actual") or "").strip()
    for name, val in (("expected", expected), ("actual", actual)):
        if not val:
            block(name, f"{name} is empty: say what you expected and what came back.", name)

    args = rep.get("arguments")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        block("arguments", "arguments must be the JSON object sent to the tool ({} if none).", "arguments")
        args = {}
    clean_args = redact_args(args, terms)
    excerpt = redact_text(rep["response_excerpt"], terms).strip() if rep.get("response_excerpt") else ""

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

    what = str(rep.get("what_i_tried") or "").strip() or (
        f"Called {tool} with the arguments in the reproduction below the feedback, and compared what came back "
        "with the tool's description.")
    suggestion = str(rep.get("suggestion") or "").strip()

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


def classify_error(err):
    if CONTEXT_ERROR.search(err):
        return "rejected", "context", True, ("Loomi Connect refused it for access reasons. Stop: check the connection "
                                             "and the user's access before anything else.")
    if RATE_ERROR.search(err):
        return "rejected", "rate_limited", True, ("Rate-limited, so nothing was recorded. Wait at least the Retry-After "
                                                  "time (the tool allows one report every 10 seconds), then ask the "
                                                  "user again before sending.")
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
        err = error_of(data) if data is not None else (text if re.search(r"\berror\b|\bfailed\b", text, re.I) else None)
        if err is not None:
            state, reason, stop, note = classify_error(err)
            res.update(state=state, reason=reason, stop=stop, error=redact_text(err)[:200], note=note)
        else:
            fid = find_id(data) if isinstance(data, dict) else None
            ok = (isinstance(data, dict) and (data.get("success") is True or
                  (isinstance(data.get("result"), dict) and data["result"].get("success") is True))) or bool(fid) \
                or bool(SUCCESS_WORDS.search(text))
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
    b.add_argument("--report", required=True, help="ONE report as JSON (references/report-format.md)")
    b.add_argument("--environment", required=True, choices=RULES["environments"],
                   help="where the problem happened; required, no default")
    b.add_argument("--known-doc", help="path of docs/known-tool-behaviour.md, needed when the report has known_line")
    b.add_argument("--private-terms", help="file of names the user flagged as private (customer, brand), one per line")
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
