#!/usr/bin/env python3
"""Pre-launch checks for one Bloomreach Engagement weblayer (banner).

Usage:
  python3 weblayer_checks.py banner.json [--now 2026-11-03T12:00:00Z] [--out findings.json]

banner.json is the raw JSON returned by the Loomi Connect search_banners tool with a
banner_id (one weblayer's details). Each variant's source code (html, style, script, with
[[ ]] parameters in place) is checked against the platform rules: the skeleton, tracking,
closing, template parameters, Jinja, links, external loads and unsafe code. Parameters in
links are filled in from the variant's current values (params) before the links are checked.

Prints JSON (or writes it to --out): findings per variant and for the whole weblayer, each
with a severity (blocker, warning, nitpick), the links to load, external loads, storage
access, what couldn't be checked, and a suggested verdict. The word lists and thresholds are
in references/rules.json. Standard library only; no network access: links are listed for
loading, not loaded.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

RULES = json.loads((Path(__file__).resolve().parent.parent / "references" / "rules.json").read_text(encoding="utf-8"))
ORDER = {"blocker": 0, "warning": 1, "nitpick": 2}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PARAM = re.compile(r"\[\[(.*?)\]\]", re.S)
JINJA_OPEN = {"if", "for", "macro", "call", "filter", "raw", "block", "with", "autoescape"}
SAFE_SCHEMES = ("http://", "https://", "//", "/", "#", "mailto:", "tel:", "sms:", "{{", "data:")
SVG_NS = ("http://www.w3.org/",)


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for d in (data, data.get("result") if isinstance(data, dict) else None):
        if isinstance(d, dict) and d.get("success") is False:
            fail(f"{path}: Loomi Connect returned an error: {d.get('error') or d.get('message') or 'no error text'}. "
                 "This check couldn't run; don't treat it as 'nothing found'.")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict) or not isinstance(data.get("variants"), list):
        fail(f"{path}: not a search_banners detail result (no variants). Call search_banners with banner_id.")
    return data


def expected_load(target):
    """True if a load is one the platform skeleton needs: a relative path under an allowed path, or an
    exact allowed host with an allowed path prefix. Substring matches would let evil.tld/brstatic/ through."""
    a = RULES["allowed_loads"]
    if target.startswith("/") and not target.startswith("//"):
        return any(target.startswith(p) for p in a["relative_paths"])
    try:
        u = urlsplit(target if not target.startswith("//") else "https:" + target)
    except ValueError:
        return False
    if u.scheme != "https" or not u.hostname:
        return False
    for entry in a["hosts"]:
        host, _, path = entry.partition("/")
        if u.hostname == host and (not path or u.path.startswith("/" + path)):
            return True
    return False


def excerpt(s):
    s = EMAIL.sub("<email>", " ".join(str(s).split()))
    n = RULES["excerpt_chars"]
    return s if len(s) <= n else s[:n - 1] + "…"


def ts(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc)
    t = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- template parameters
def parse_params(code):
    """Every [[ ]] parameter in a piece of code: name, type, default, problems."""
    out = []
    for m in PARAM.finditer(code):
        body = m.group(1).strip()
        p = {"raw": m.group(0), "problems": []}
        if body.startswith("{"):
            depth, end = 0, -1
            for i, ch in enumerate(body):
                depth += ch == "{"
                depth -= ch == "}"
                if depth == 0:
                    end = i
                    break
            meta, rest = (body[:end + 1], body[end + 1:]) if end >= 0 else (body, "")
            nm = re.search(r"name\s*:\s*['\"]([^'\"]+)['\"]", meta)
            p["name"] = nm.group(1) if nm else None
            if not nm:
                p["problems"].append("has no name")
            if not re.search(r"isJsonParam\s*:\s*true", meta):
                p["problems"].append("lacks isJsonParam: true, so the panel shows the whole {...} as its name")
        else:
            nm = re.match(r"([^:|]+)", body)
            p["name"] = nm.group(1).strip() if nm else None
            rest = body[len(nm.group(1)):] if nm else body
        rest = rest.strip()
        typ, default = "string", None
        if rest.startswith(":"):
            rest = rest[1:]
            typ, _, default = rest.partition("|")
            typ, default = typ.strip() or "string", (default.strip() if _ else None)
        elif rest.startswith("|"):
            default = rest[1:].strip()
        p["type"], p["default"] = typ, default
        base = typ.split("(")[0].strip().lower()
        if base not in RULES["param_types"]:
            p["problems"].append(f"has unknown type '{typ}'")
        if base == "number" and default not in (None, "") and not re.fullmatch(r"-?\d+(\.\d+)?", default):
            p["problems"].append(f"is a number with a non-numeric default '{default}'")
        if base in ("string", "text") and default and '"' in default:
            p["problems"].append("has a default containing a double quote, which ends the JavaScript string or {% set %} early")
        out.append(p)
    return out


def fill(text, values, params):
    """Replace [[ ]] parameters with their current value, or their default."""
    defaults = {p["name"]: p["default"] for p in params if p.get("name")}
    def rep(m):
        name = next((p["name"] for p in params if p["raw"] == m.group(0)), None)
        if name in values and values[name] not in (None, ""):
            return str(values[name])
        return defaults.get(name) or ""
    return PARAM.sub(rep, text)


# ---------------------------------------------------------------- HTML
class Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.text, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag in ("style", "script", "svg"):
            self.skip += 1

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        if tag in ("style", "script", "svg") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.text.append(data.strip())


def strip_templates(s):
    s = PARAM.sub(" ", s)
    s = re.sub(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", " ", s, flags=re.S)
    return re.sub(r"<!--.*?-->", " ", s, flags=re.S)


def is_close(attrs):
    hay = " ".join(str(attrs.get(k) or "") for k in ("class", "id", "aria-label", "data-action")).lower()
    return "close" in hay or "dismiss" in hay


# ---------------------------------------------------------------- links
def link_problems(url):
    u = url.strip()
    low = u.lower()
    if low.startswith("javascript:"):
        return "blocker", "runs code (javascript: URL)"
    if u in ("", "#"):
        return "warning", "is a placeholder (empty or '#')"
    if not low.startswith(SAFE_SCHEMES):
        return "warning", "has no https:// scheme, so it's treated as a relative link"
    m = re.match(r"(?:https?:)?//([^/?#:]+)([^#]*)", u, re.I)
    if m:
        host, rest = m.group(1).lower(), m.group(2).lower()
        if any(host == h or host.endswith("." + h) for h in RULES["placeholder_hosts"]):
            return "warning", f"points at a placeholder host ({host})"
        if low.startswith("http://") and not low.startswith(SVG_NS):
            return "warning", "uses http://, which browsers block or warn about on an https site"
        words = [w for w in RULES["placeholder_words"] if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", rest)]
        if words:
            return "warning", f"looks like a placeholder ('{words[0]}' in the path); confirm the real URL"
    return None, None


# ---------------------------------------------------------------- JavaScript helpers
def function_body(script, name):
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", script)
    if not m:
        return None
    depth, i = 1, m.end()
    while i < len(script) and depth:
        depth += script[i] == "{"
        depth -= script[i] == "}"
        i += 1
    return script[m.end():i - 1]


def without_comments(js):
    js = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    return re.sub(r"(?m)(^|[^:\\'\"])//[^\n]*", r"\1", js)


def jinja_problems(code):
    probs = []
    stack = []
    for m in re.finditer(r"\{%-?\s*(\w+)([^%]*)%\}", code):
        tag, rest = m.group(1), m.group(2)
        if tag in JINJA_OPEN or (tag == "set" and "=" not in rest):
            stack.append(tag)
        elif tag.startswith("end"):
            want = tag[3:]
            if not stack or stack[-1] != want:
                probs.append(f"{{% {tag} %}} has no matching {{% {want} %}}")
                if want in stack:
                    while stack and stack.pop() != want:
                        pass
            else:
                stack.pop()
    probs += [f"{{% {t} %}} is never closed" for t in stack]
    if re.search(r"\{%(?![\s\S]*?%\})", code):
        probs.append("a {% tag is never closed with %}")
    for m in re.finditer(r"\{\{", code):
        nxt_close, nxt_open = code.find("}}", m.end()), code.find("{{", m.end())
        if nxt_close < 0 or (0 <= nxt_open < nxt_close):
            probs.append("a {{ expression is never closed with }}")
            break
    return probs


# ---------------------------------------------------------------- checks
def check_variant(v):
    html, style, script = v.get("html") or "", v.get("style") or "", v.get("script") or ""
    values = v.get("params") or {}
    found = []

    def add(sev, check, detail, fix, where=None):
        found.append({"severity": sev, "check": check, "where": where, "detail": detail, "fix": fix})

    params = parse_params(html) + parse_params(style) + parse_params(script)
    js = without_comments(script)
    skeleton = "utils" if re.search(r"\butils\.(setConfig|registerStartTrigger)\s*\(", js) else "legacy"

    # Template parameters
    for code, where in ((html, "html"), (style, "css"), (script, "javascript")):
        if code.count("[[") != code.count("]]"):
            add("blocker", "parameters", "a [[ parameter isn't closed with ]] (or a ]] has no [[)",
                "Close every parameter: [[ {name: 'X', isJsonParam: true} : type | default ]]", where)
    seen, by_name = set(), {}
    for p in params:
        for pr in p["problems"]:
            key = (p.get("name"), pr)
            if key not in seen:
                seen.add(key)
                sev = "nitpick" if pr.startswith("has unknown type") and p["type"].lower() in ("url", "html", "font") else "warning"
                add(sev, "parameters", f"Parameter '{p.get('name') or excerpt(p['raw'])}' {pr}",
                    "Fix the parameter definition (see the parameter syntax in references/check-catalog.md)")
        if p.get("name"):
            by_name.setdefault(p["name"], set()).add(p["type"].lower())
    for name, types in sorted(by_name.items()):
        if len(types) > 1:
            add("warning", "parameters", f"Parameter '{name}' is used with different types ({', '.join(sorted(types))})",
                "Give every use of the parameter the same type and default")
    declared = set(by_name)
    stale = sorted(set(values) - declared)
    if stale:
        add("nitpick", "parameters", f"{len(stale)} saved parameter value(s) not used in the code: {', '.join(stale[:RULES['list_limit']])}",
            "Leftovers from an earlier version; harmless, but confirm nothing was removed by mistake")
    timing = [n for n in sorted(declared | set(values)) if any(re.search(pat, n, re.I) for pat in RULES["timing_param_patterns"])]
    if timing or re.search(r"PARAM_(trigger|showAfter)\b", js):
        add("warning", "triggering", "Triggering code in parameters: " + ", ".join(timing or ["PARAM_trigger / PARAM_showAfter"]),
            "Remove it and set the timing in Settings > Smart triggering; with both, the weblayer shows unpredictably")
    listeners = sorted(set(re.findall(r"addEventListener\(\s*['\"](" + "|".join(RULES["timing_listener_events"]) + r")['\"]", js)))
    if listeners:
        add("warning", "triggering", "Listeners that usually mean triggering code: " + ", ".join(listeners),
            "If they decide when the weblayer appears, remove them and use Smart triggering (exit intent, scroll position)")

    # Skeleton and runtime rules
    tail = re.sub(r"[\s;]+$", "", js)
    if not re.search(r"return\s*\{\s*remove\s*:[^;]*\}$", tail):
        add("blocker", "skeleton", "The JavaScript doesn't end with return { remove: removeBanner }",
            "Make `return { remove: removeBanner }` the last line, so Bloomreach can remove the weblayer", "javascript")
    if skeleton == "utils":
        if re.search(r"\b(const|let|var)\s+utils\b", js):
            add("blocker", "skeleton", "`utils` is redeclared, which breaks the weblayer silently",
                "Delete the declaration: utils is a global loaded by the skeleton", "javascript")
        for call in ("utils.setConfig", "utils.registerStartTrigger"):
            if call + "(" not in js:
                add("blocker", "skeleton", f"{call}() is never called, so the weblayer never starts",
                    "Restore the skeleton's start block (see references/check-catalog.md)", "javascript")
        body = function_body(js, "createBanner")
        if body is None:
            add("blocker", "skeleton", "There's no createBanner() function", "Restore the skeleton's createBanner()", "javascript")
        else:
            stmts = [s.strip() for s in re.split(r"[;\n]", body) if s.strip() and s.strip() != "}"]
            if "utils.attachBannerToDom(" not in body:
                add("blocker", "skeleton", "createBanner() never calls utils.attachBannerToDom(banner), so nothing renders",
                    "Add `utils.attachBannerToDom(banner)` as the last line of createBanner()", "javascript")
            elif not stmts or not stmts[-1].startswith("utils.attachBannerToDom("):
                add("warning", "skeleton", "utils.attachBannerToDom(banner) isn't the last line of createBanner()",
                    "Move it to the end, after event handlers are attached", "javascript")
            root = re.search(r"placeholder\.querySelector\(\s*['\"]([.#])([\w-]+)['\"]", body)
            if root:
                kind, name = root.groups()
                attr = "class" if kind == "." else "id"
                if not re.search(attr + r"\s*=\s*['\"][^'\"]*\b" + re.escape(name) + r"\b", html):
                    add("blocker", "skeleton", f"createBanner() looks for '{kind}{name}', but no HTML element has that {attr}",
                        f"Give the HTML root {attr}=\"{name}\", or change the selector to match", "javascript")
        load_fn = function_body(js, "loadScript") or ""
        outside = js.replace(load_fn, "")
        if re.search(r"document\.(querySelector(All)?|getElementById|getElementsBy\w+)\s*\(", outside):
            add("warning", "skeleton", "document.querySelector() or getElementById() outside loadScript() can hit the host page",
                "Query inside the weblayer with banner.querySelector()", "javascript")
        if re.search(r"sdk\.track\(\s*['\"]banner['\"]\s*,\s*\{", js):
            add("warning", "tracking", "A banner event is built by hand, which loses the banner and variant IDs",
                "Use self.sdk.track(\"banner\", utils.getEventProperties(\"<action>\"))", "javascript")
        if "handleCloseButtonClick" not in js:
            add("warning", "tracking", "The close button doesn't use utils.handleCloseButtonClick, so 'close' may not be tracked",
                "Bind it: closeBtn.onclick = utils.handleCloseButtonClick.bind(utils)", "javascript")
    else:
        add("nitpick", "skeleton", "Built on an older template, not the current utils skeleton. It can still work; the runtime rules below were checked",
            "No change needed for launch. Rebuild on the current skeleton (engagement-weblayer-builder) at the next redesign")
        if not re.search(r"insertAdjacentHTML|appendChild|insertBefore|\.prepend\(|\.append\(|attachBannerToDom", js):
            add("blocker", "skeleton", "Nothing inserts the weblayer into the page", "Insert the weblayer element into the page", "javascript")
        if not re.search(r"\.track\(\s*['\"]banner['\"]", js):
            add("warning", "tracking", "No banner events (show, click, close) are tracked, so the weblayer's results can't be reported",
                "Track them with self.sdk.track(\"banner\", ...)", "javascript")
    for pat, what in ((r"\beval\s*\(", "eval()"), (r"document\.write\s*\(", "document.write()"), (r"new\s+Function\s*\(", "new Function()")):
        if re.search(pat, js):
            add("blocker", "unsafe code", f"Uses {what}, which can run injected code on the storefront",
                "Remove it; build elements and set textContent or setAttribute", "javascript")
    risky = [m.group(0) for m in re.finditer(r"(\.innerHTML|\.outerHTML)\s*[+]?=\s*[^;\n]*|insertAdjacentHTML\([^)]*\)", js)
             if not re.search(r"self\.(html|style)|['\"]\s*\)?\s*$", m.group(0))]
    if risky:
        add("warning", "unsafe code", f"{len(risky)} place(s) put a value in as HTML, e.g. `{excerpt(risky[0])}`",
            "If the value can come from Jinja, a catalog, the URL or a form, set textContent or setAttribute instead", "javascript")
    if re.search(r"\bdebugger\b", js):
        add("warning", "leftovers", "A `debugger` statement is left in", "Remove it", "javascript")
    logs = len(re.findall(r"console\.(log|debug|info)\s*\(", js))
    if logs:
        add("nitpick", "leftovers", f"{logs} console.log/debug/info call(s) left in", "Remove them, or keep only console.error in catch blocks", "javascript")
    if re.search(r"sdk\.identify\(\s*[\w.]+\s*\)", js):
        add("warning", "identify", "self.sdk.identify() is called with a plain value, which sets the `registered` hard ID",
            "Confirm the project stores email in registered; otherwise pass {email_id: email}", "javascript")

    # HTML structure, closing and accessibility
    scan = Scan()
    scan.feed(strip_templates(html))
    names = [t for t, _ in scan.tags]
    if any(t in names for t in ("html", "head", "body")):
        add("blocker", "skeleton", "The HTML has <html>, <head> or <body> tags", "Remove them: the weblayer is inserted into an existing page", "html")
    closers = [(t, a) for t, a in scan.tags if is_close(a)]
    css = fill(style, values, params)
    overlay = bool(re.search(r"position\s*:\s*fixed", css)) or str(values.get("WeblayerType", "")).lower() == "pop-up"
    if overlay and not closers:
        if re.search(r"100vh|inset\s*:\s*0|height\s*:\s*100%", css):
            add("blocker", "closing", "A full-screen pop-up with no close button traps visitors on the page",
                "Add a close button wired to the close handler", "html")
        else:
            add("warning", "closing", "A fixed weblayer with no close button can't be dismissed",
                "Add a close button, or confirm it should stay on screen", "html")
    # A close control whose only content is an icon, with no aria-label or title, has no accessible name.
    for m in re.finditer(r"<(button|a|div|span)\b([^>]*)>\s*(<svg|<img|&times;|×|✕|x\s*<)", html, re.I):
        attrs = m.group(2).lower()
        if ("close" in attrs or "dismiss" in attrs) and "aria-label" not in attrs and "title=" not in attrs:
            add("warning", "accessibility", "The close button has no aria-label, so screen readers announce nothing",
                "Add aria-label=\"Close\"", "html")
            break
    raw_scan = Scan()
    raw_scan.feed(html)
    no_alt = sum(1 for t, a in raw_scan.tags if t == "img" and "alt" not in a)
    if no_alt:
        add("nitpick", "accessibility", f"{no_alt} image(s) have no alt attribute", "Add alt text (alt=\"\" for decorative images)", "html")

    # Hard-coded values that should be parameters
    copy = [t for t in scan.text if len(re.findall(r"[A-Za-z]", t)) >= RULES["copy_min_chars"]]
    if copy:
        add("nitpick", "parameters", f"{len(copy)} piece(s) of copy are hard-coded, e.g. " + "; ".join(f"'{excerpt(c)}'" for c in copy[:RULES["list_limit"]]),
            "Make each a string or text parameter in the Content category", "html")
    plain_css = strip_templates(style) + " " + " ".join(re.findall(r"style\s*=\s*\"([^\"]*)\"", strip_templates(html)))
    plain_css = re.sub(r"xmlns(:\w+)?=\S+", " ", plain_css)
    colours = sorted(set(re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)", plain_css)))
    if colours:
        add("nitpick", "parameters", f"{len(colours)} colour(s) are hard-coded, e.g. {', '.join(colours[:RULES['list_limit']])}",
            "Make each colour a color parameter in the Branding category", "css")
    fonts = sorted(set(f.strip() for f in re.findall(r"font-family\s*:\s*([^;}{]+)", plain_css) if f.strip() and f.strip() not in ("inherit", "initial")))
    if fonts:
        add("nitpick", "parameters", f"Font family hard-coded: {', '.join(fonts[:RULES['list_limit']])}",
            "Make the font family a parameter (an enum for a choice of fonts)", "css")
    hard_imgs = [a.get("src") for t, a in scan.tags if t == "img" and re.match(r"(https?:)?//", a.get("src") or "")]
    hard_imgs += re.findall(r"url\(\s*['\"]?((?:https?:)?//[^'\")]+)", strip_templates(style))
    if hard_imgs:
        add("warning", "parameters", f"{len(hard_imgs)} image URL(s) are hard-coded, e.g. {excerpt(hard_imgs[0])}",
            "Make every image an image parameter, so it can be changed without editing code", "html")

    # Jinja
    for code, where in ((html, "html"), (style, "css"), (script, "javascript")):
        for pr in jinja_problems(PARAM.sub("", code)):
            add("blocker", "jinja", pr.capitalize(), "Balance the Jinja tags", where)
    allcode = PARAM.sub("", html + style + script)
    for expr in sorted(set(re.findall(r"\{\{\s*customer[.\[][^}]*\}\}", allcode))):
        if "default(" not in expr:
            add("warning", "jinja", f"{excerpt(expr)} has no fallback; anonymous visitors see 'None' or nothing",
                "Add | default('there', true)")
        elif re.search(r"default\(\s*[^,()]+\s*\)", expr):
            add("warning", "jinja", f"{excerpt(expr)} uses default() without true, which doesn't replace None or ''",
                "Use | default('…', true)")
    if re.search(r"\{%\s*for\s+\w+\s+in\s+aggregates\[", allcode) and "'None'" not in allcode and '"None"' not in allcode:
        add("warning", "jinja", "A loop over an aggregate has no guard; an empty aggregate renders as the string 'None' and loops over its letters",
            "Wrap it: {% set x = aggregates['<id>'] %}{% if x and x != 'None' %}…{% endif %}")

    # Links (parameters filled in with current values)
    links = []
    filled_html = fill(html, values, params)
    fscan = Scan()
    fscan.feed(filled_html)
    for t, a in fscan.tags:
        for attr in ("href", "src"):
            if attr in a and not (attr == "href" and is_close(a)) and t not in ("script", "link"):
                links.append({"where": f"<{t} {attr}>", "url": (a.get(attr) or "").strip(), "tag": t})
    for name, val in sorted(values.items()):
        if isinstance(val, str) and (re.search(r"(link|url|href)$", name, re.I) or re.match(r"https?://", val)):
            links.append({"where": f"parameter {name}", "url": val.strip(), "tag": "param"})
    uniq = {}
    for ln in links:
        if "{{" in ln["url"] or "{%" in ln["url"] or (ln["tag"] == "img" and ln["url"] == ""):
            continue
        uniq.setdefault(ln["url"], ln)
    for url, ln in uniq.items():
        sev, why = link_problems(url)
        if sev:
            add(sev, "links", f"{ln['where']} {why}: {excerpt(url) or '(empty)'}", "Replace it with the real https:// URL")
    image_params = [p["name"] for p in params if p["type"].lower() == "image" and p.get("name")]
    empty_imgs = sorted({n for n in image_params if not str(values.get(n) or "").strip() and not any(
        q["name"] == n and q["default"] for q in params)})
    if empty_imgs:
        add("nitpick", "parameters", f"Image parameter(s) with no image set: {', '.join(empty_imgs)}",
            "Set an image, or confirm the layout works without one")

    # External loads, network calls and storage
    loads = []
    for m in re.finditer(r"<script[^>]*\ssrc\s*=\s*['\"]([^'\"]+)|<link[^>]*\shref\s*=\s*['\"]([^'\"]+)", html, re.I):
        loads.append({"kind": "html", "target": m.group(1) or m.group(2)})
    for m in re.finditer(r"@import\s+(?:url\()?['\"]?([^'\");]+)", style):
        loads.append({"kind": "css @import", "target": m.group(1)})
    for m in re.finditer(r"(loadScript|loadStylesheet|fetch|import|sendBeacon)\s*\(\s*['\"`]([^'\"`]+)", js):
        loads.append({"kind": m.group(1), "target": m.group(2)})
    for m in re.finditer(r"['\"`](https?://[^'\"`\s]+)", js):
        if not m.group(1).startswith(SVG_NS) and not any(l["target"] == m.group(1) for l in loads):
            loads.append({"kind": "URL in script", "target": m.group(1)})
    for kind in ("XMLHttpRequest", "fetch(", "sendBeacon("):
        if kind in js and not any(l["kind"] == kind.rstrip("(") for l in loads):
            loads.append({"kind": kind.rstrip("("), "target": "(computed URL)"})
    for l in loads:
        l["expected"] = expected_load(l["target"])
        # Query strings can hold API keys; report the target without one.
        l["target"] = excerpt(l["target"].split("?", 1)[0])
    unexpected = [l for l in loads if not l["expected"]]
    if unexpected:
        add("warning", "external loads", f"{len(unexpected)} external load(s) or network call(s) the skeleton doesn't need, e.g. {excerpt(unexpected[0]['target'])}",
            "Confirm each with the weblayer's owner; it's third-party code on the storefront")
    storage = sorted(set(re.findall(r"document\.cookie|localStorage|sessionStorage", js)))
    data_uris = [len(u) * 3 // 4 // 1024 for u in re.findall(r"data:[\w/+.-]+;base64,[A-Za-z0-9+/=]+", html + style + script)]
    big = [k for k in data_uris if k > RULES["max_data_uri_kb"]]
    if big:
        add("warning", "size", f"{len(big)} inline data: URI(s) over {RULES['max_data_uri_kb']} KB (largest {max(big)} KB)",
            "Upload the asset and use an image parameter instead")
    kb = len((html + style + script).encode("utf-8")) // 1024
    if kb > RULES["max_source_kb"]:
        add("nitpick", "size", f"The code is {kb} KB", "Trim unused CSS and JavaScript")

    found.sort(key=lambda f: ORDER[f["severity"]])
    return {"id": v.get("id"), "name": v.get("name"), "enabled": v.get("enabled", True), "percentage": v.get("percentage"),
            "skeleton": skeleton, "findings": found,
            "links_to_load": [{"where": ln["where"], "url": u} for u, ln in uniq.items() if re.match(r"(https?:)?//", u)],
            "external_loads": loads, "storage_access": storage, "size_kb": kb}


def check_banner(b, now):
    found, not_checked = [], []

    def add(sev, check, detail, fix):
        found.append({"severity": sev, "check": check, "where": None, "detail": detail, "fix": fix})

    variants = b.get("variants") or []
    on = [v for v in variants if v.get("enabled", True)]
    if not on:
        add("blocker", "variants", "No variant is enabled, so nothing shows", "Enable a variant")
    else:
        total = sum(float(v.get("percentage") or 0) for v in on)
        if abs(total - 100) > 0.01:
            add("blocker", "variants", f"Enabled variants' traffic adds up to {total:g}%, not 100%", "Make the percentages total 100")
    trig = b.get("trigger")
    if isinstance(trig, dict):
        inc, exc = trig.get("include_pages") or [], trig.get("exclude_pages") or []
        if not inc:
            add("warning", "targeting", "No pages are included, so the weblayer may show nowhere", "Set Show on to the pages it should appear on")
        elif any((p or {}).get("type") == "any" for p in inc) and not exc:
            add("nitpick", "targeting", "Shows on every page, including checkout and account pages",
                "Exclude pages where a pop-up gets in the way, or confirm every page is intended")
    else:
        not_checked.append("page targeting (no trigger in the response)")
    if b.get("customer_filter") in (None, {}, {"filters": [], "formula": ""}):
        not_checked.append("audience: no customer filter, so every visitor is eligible (information, not a problem)")
    df = b.get("date_filter")
    if isinstance(df, dict) and df.get("enabled"):
        end = ts(df.get("to") or df.get("end") or df.get("until"))
        if end is None:
            add("nitpick", "schedule", "The schedule has no end date", "Set an end date for a time-limited promotion")
        elif end < now:
            add("blocker", "schedule", f"The schedule ended on {end.date().isoformat()}, so the weblayer won't show", "Move the end date")
    elif "date_filter" not in b:
        not_checked.append("schedule (not in the banner details; use search_banners with serving_status)")
    elif not df or not df.get("enabled"):
        add("nitpick", "schedule", "No schedule: it runs until someone turns it off", "Set an end date for a time-limited promotion")
    not_checked.append("smart triggering conditions (Loomi Connect doesn't return them)")
    return found, not_checked


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("banner", help="saved search_banners detail result (one banner_id)")
    ap.add_argument("--now", help="ISO time to judge schedules against (default: current UTC time)")
    ap.add_argument("--out", help="write the JSON here instead of printing it")
    a = ap.parse_args()
    b = load(a.banner)
    now = ts(a.now) if a.now else datetime.now(timezone.utc)
    variants = [check_variant(v) for v in b["variants"]]
    banner_findings, not_checked = check_banner(b, now)
    # A disabled variant never shows: its findings are reported but don't count towards the verdict.
    every = banner_findings + [f for v in variants if v["enabled"] for f in v["findings"]]
    counts = {s: sum(1 for f in every if f["severity"] == s) for s in ORDER}
    verdict = "NO-GO" if counts["blocker"] else "GO WITH CAUTION" if counts["warning"] else "GO"
    result = {"ok": True, "banner": {"id": b.get("_id"), "name": b.get("name"), "status": b.get("status")},
              "verdict": verdict, "counts": counts,
              "verdict_note": "Before links are loaded. Any primary link that can't be loaded caps the verdict at GO WITH CAUTION.",
              "banner_findings": banner_findings, "variants": variants, "not_checked": not_checked}
    out = json.dumps(result, indent=2, ensure_ascii=False)
    if a.out:
        Path(a.out).write_text(out + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "out": a.out, "verdict": verdict, "counts": counts}))
    else:
        print(out)


if __name__ == "__main__":
    main()
