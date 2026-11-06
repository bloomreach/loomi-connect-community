#!/usr/bin/env python3
"""Any ESP's HTML email export -> Bloomreach Engagement (BEE template + jinja_html + scenario payload).

Works on any table- or div-based HTML email. Detects which ESP the export came from (Mailchimp,
Salesforce Marketing Cloud, HubSpot, Braze, Iterable, ActiveCampaign, Klaviyo, other Jinja/Liquid,
or plain HTML), lists every merge tag and template block it holds, and translates the common ones
(name, email, unsubscribe, view in browser, company name and address, year) by itself. Everything
else is translated through mapping.json, so a token the script doesn't know is never guessed.

Subcommands
  setup    --venv DIR
      Create a virtual environment at DIR (standard library only, no network) and print the
      pip command that installs beautifulsoup4 and jinja2 into it.
  analyze  <export.html> --out-dir DIR [--esp NAME]
      Parse the export into DIR/model.json and print a migration report (JSON): the ESP it
      looks like, every distinct template token (with the automatic translation, if any),
      images and their hosts, dead links, placeholder copy, hard-coded discount codes.
  build    --model DIR/model.json --mapping mapping.json --meta meta.json --out-dir DIR
      Translate every token to Bloomreach Jinja (mapping.tokens first, then the built-in rules),
      then write DIR/bee.json, DIR/email.html, DIR/payload.json (create_scenario payload) and
      print a change log + lint result. Exit code 1 if lint finds blocking errors.
  render-check --html DIR/email.html --context ctx.json
      Render jinja_html locally with Jinja2 against real project data (customer properties,
      catalog items, trigger event) to catch template errors before pushing.

Every subcommand except setup takes --venv DIR and re-runs itself with that environment's
Python, so beautifulsoup4 and jinja2 never need installing into the system Python.
"""
import argparse, copy, datetime, html as htmllib, json, os, re, secrets, sys, time, uuid

# ----------------------------------------------------------------------------------------------
# virtual environment: create it (setup), or re-run this script with its Python (--venv)
# ----------------------------------------------------------------------------------------------
def venv_python(venv):
    return os.path.join(venv, "Scripts", "python.exe") if os.name == "nt" else os.path.join(venv, "bin", "python3")

def bootstrap_venv(argv):
    if "--venv" not in argv or argv.index("--venv") + 1 >= len(argv):
        return
    venv = os.path.realpath(argv[argv.index("--venv") + 1])
    skill_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
    if os.path.commonpath([venv, skill_dir]) == skill_dir:
        sys.exit(json.dumps({"ok": False, "error": "Put the venv in your working folder, not inside the skill's folder"}))
    if len(argv) > 1 and argv[1] == "setup":
        import venv as venvlib
        try:
            venvlib.create(venv, with_pip=True)
        except Exception as e:
            sys.exit(json.dumps({"ok": False, "error": f"Couldn't create the venv: {e}"}))
        pip = os.path.join(os.path.dirname(venv_python(venv)), "pip")
        print(json.dumps({"ok": True, "venv": venv, "next": f"{pip} install beautifulsoup4 jinja2"}))
        sys.exit(0)
    if os.path.realpath(sys.prefix) != venv:
        py = venv_python(venv)
        if not os.path.exists(py):
            sys.exit(json.dumps({"ok": False, "error": f"No venv at {venv}; run setup --venv {venv} first"}))
        if os.name == "nt":
            # On Windows os.execv starts a new process and this one exits with code 0, which would hide the
            # build's lint failures (exit 1). Run the venv's Python as a child and pass its exit code on.
            import subprocess
            sys.exit(subprocess.run([py, os.path.realpath(__file__)] + argv[1:]).returncode)
        os.execv(py, [py, os.path.realpath(__file__)] + argv[1:])

bootstrap_venv(sys.argv)

try:
    from bs4 import BeautifulSoup, NavigableString, Comment
except ImportError:
    if "-h" in sys.argv or "--help" in sys.argv:  # help needs no packages
        BeautifulSoup = NavigableString = Comment = None
    else:
        sys.exit(json.dumps({"ok": False, "error": "beautifulsoup4 isn't installed: run setup --venv <work>/.venv, install with its pip, then pass --venv"}))

# ----------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------
def uid():
    return str(uuid.uuid4())

def parse_style(s):
    out = {}
    for part in (s or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            k, v = k.strip().lower(), v.strip().replace('"', "'")
            if k and v:
                out.pop(k, None)
                out[k] = re.sub(r"'(serif|sans-serif|monospace|cursive)'", r"\1", v)
    if "margin" not in out and "padding" not in out:
        return out
    # Expand margin/padding shorthands into longhands, in declaration order, so that merging two style dicts
    # can't let a shorthand silently override a later longhand (or the other way round).
    exp = {}
    for k, v in out.items():
        if k in ("margin", "padding"):
            parts = v.replace("!important", "").split()
            if not parts or len(parts) > 4:
                exp.pop(k, None); exp[k] = v; continue
            if len(parts) == 1: parts = parts * 4
            elif len(parts) == 2: parts = parts * 2
            elif len(parts) == 3: parts = parts + [parts[1]]
            for side, val in zip(("top", "right", "bottom", "left"), parts):
                exp.pop(f"{k}-{side}", None); exp[f"{k}-{side}"] = val
        else:
            exp.pop(k, None); exp[k] = v
    return exp

def style_str(d):
    return ";".join(f"{k}:{v}" for k, v in d.items() if v not in (None, ""))

def px(v, default="0px"):
    if v is None or v == "":
        return default
    v = str(v).strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", v):
        return f"{v}px"
    return v

def first(d, *keys, default=None):
    for k in keys:
        if d.get(k):
            return d[k]
    return default

def padding_of(st):
    """Expand padding shorthand + longhands into a 4-side dict."""
    p = {"top": "0px", "right": "0px", "bottom": "0px", "left": "0px"}
    # apply declarations in source order: a later shorthand overrides an earlier longhand (CSS cascade)
    for k, v in st.items():
        v = v.replace("!important", "").strip()
        if k == "padding":
            parts = v.split()
            if len(parts) == 1: parts *= 4
            elif len(parts) == 2: parts = [parts[0], parts[1], parts[0], parts[1]]
            elif len(parts) == 3: parts = [parts[0], parts[1], parts[2], parts[1]]
            for side, val in zip(("top", "right", "bottom", "left"), parts[:4]):
                p[side] = px(val)
        elif k.startswith("padding-") and k[8:] in p:
            p[k[8:]] = px(v)
    return p

def add_px(a, b):
    def n(x):
        m = re.match(r"-?\d+(\.\d+)?", str(x) or "0")
        return float(m.group(0)) if m else 0.0
    t = n(a) + n(b)
    return f"{int(t) if t.is_integer() else t}px"

JINJA_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
CONTROL_RE = re.compile(r"\{%\s*(for|if|catalog|with|ifequal|ifnotequal)\b")

# ----------------------------------------------------------------------------------------------
# ESP detection and template tokens
# ----------------------------------------------------------------------------------------------
ESPS = ("mailchimp", "sfmc", "hubspot", "braze", "iterable", "activecampaign", "klaviyo")

ESP_SIGNALS = {
    "mailchimp": [r"\*\|[A-Z0-9_]+(?::[^|]*)?\|\*", r"\bmc:(?:edit|repeatable|hideable)\b", r"\bmcn[A-Z]\w+",
                  r"list-manage\.com", r"mcusercontent\.com", r"gallery\.mailchimp\.com"],
    "sfmc": [r"%%\[", r"%%=", r"%%[A-Za-z_][\w-]*%%", r"exacttarget\.com|exct\.net|sfmc-content\.com"],
    "hubspot": [r"\{\{\s*contact\.", r"\bunsubscribe_link(?:_all)?\b", r"\bsite_settings\.",
                r"hubspotusercontent|hubspot\.net|hs-sites\.com", r"\{%\s*(?:module|dnd_area|dnd_section|widget_block)\b"],
    "braze": [r"\$\{[A-Za-z_][\w]*\}", r"custom_attribute\.\$\{", r"braze-images\.com|appboy-images\.com|braze\.com",
              r"\{%\s*(?:connected_content|abort_message|catalog_items)\b"],
    "iterable": [r"\{\{[#/](?:if|each|unless|with)\b", r"\bdefaultIfEmpty\b",
                 r"\{\{\s*(?:unsubscribeUrl|unsubscribeMessageTypeUrl|hostedUnsubscribeUrl|viewInBrowserUrl)\s*\}\}",
                 r"iterable\.com"],
    "activecampaign": [r"%(?:FIRSTNAME|LASTNAME|FULLNAME|EMAIL|PHONE|UNSUBSCRIBELINK|UPDATELINK|WEBCOPY|SENDER-INFO[\w-]*)%",
                       r"activehosted\.com|activecampaign\.com"],
    "klaviyo": [r"\bkl-(?:row|column|text|image|button)\b", r"\{%\s*(?:unsubscribe|web_view|coupon_code|catalog)\b",
                r"\{\{\s*person\.", r"klaviyo\.com|d3k81ch9hvuctc\.cloudfront\.net"],
}

# Image hosts that belong to an ESP and usually stop serving once the account closes.
ESP_CDN = re.compile(r"mcusercontent\.com|mailchimp\.com|list-manage\.com|sfmc-content\.com|exacttarget\.com|"
                     r"exct\.net|hubspotusercontent[\w-]*\.(?:com|net)|hubspot\.net|hs-sites\.com|braze-images\.com|"
                     r"appboy-images\.com|iterable\.com|activehosted\.com|klaviyo|d3k81ch9hvuctc\.cloudfront\.net", re.I)

def token_re(esp):
    parts = [r"%%\[.*?\]%%", r"%%=.*?=%%", r"%%[A-Za-z_][\w-]*%%",          # SFMC AMPscript / personalization strings
             r"\*\|[^|*]{1,120}\|\*",                                       # Mailchimp merge tags
             r"\{\{\{.*?\}\}\}",                                             # Handlebars triple-stache
             r"\{\{[^{}]*\$\{[^{}]*\}[^{}]*\}\}",                            # Braze {{${first_name}}}
             r"\{\{.*?\}\}", r"\{%.*?%\}"]                                   # Jinja / Liquid / HubL / Handlebars
    if esp == "activecampaign":
        parts.append(r"%[A-Z][A-Z0-9_-]{2,40}%")                             # ActiveCampaign %FIRSTNAME%
    return re.compile("|".join(parts), re.S)

# A placeholder that survives HTML parsing unchanged; it stands for model["tokens"][n].
PH = "⟦T%d⟧"
PH_RE = re.compile("⟦T(\\d+)⟧")

def detect_esp(raw):
    signals = {e: sum(len(re.findall(p, raw, re.I)) for p in pats)
               for e, pats in ESP_SIGNALS.items()}
    signals = {e: n for e, n in signals.items() if n}
    if signals:
        return max(signals, key=signals.get), signals
    if re.search(r"\{\{|\{%", raw):
        return "jinja-like", signals
    return "plain", signals

def tokenize(text, esp, tokens, index):
    """Swap every template token for a placeholder; tokens/index collect the distinct sources."""
    def sub(mo):
        src = mo.group(0)
        if src not in index:
            index[src] = len(tokens); tokens.append(src)
        return PH % index[src]
    return token_re(esp).sub(sub, text)

def restore(text, tokens):
    return PH_RE.sub(lambda mo: tokens[int(mo.group(1))], text or "")

CONTROL_SRC = re.compile(r"^(?:\{%\s*(?:if|elif|elsif|else|endif|for|endfor|unless|endunless|case|when|endcase)\b|"
                         r"\{\{[#/^]|\{\{\s*else\s*\}\}|\*\|(?:IF|IFNOT|ELSEIF|ELSE|END):|%%\[)", re.I)

# ----------------------------------------------------------------------------------------------
# ANALYZE: HTML export -> block model
# ----------------------------------------------------------------------------------------------
SKIP_TAGS = {"style", "script", "head", "title", "meta", "link", "xml", "o:officedocumentsettings"}
INLINE = {"a", "span", "strong", "b", "em", "i", "u", "br", "font", "sup", "sub", "small", "s", "strike", "abbr",
          "code", "mark", "big", "wbr", "label"}
TEXT_BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "blockquote", "pre"}
TYPO_INH = ("font-family", "font-size", "font-weight", "font-style", "color", "letter-spacing", "text-transform",
            "line-height", "text-align")

def inline_css(soup):
    """Copy <head> CSS rules onto the elements they match, under each element's own inline style, because the
    Visual Builder drops <head> CSS. Media queries, @-rules and pseudo-class selectors are skipped; rules are
    applied in specificity order (ids, classes, tags), then source order."""
    css = " ".join(s.get_text() for s in soup.find_all("style"))
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    css = re.sub(r"@[\w-]+[^{;]*(?:;|\{(?:[^{}]*\{[^{}]*\})*[^{}]*\})", "", css)
    rules = []
    for order, (sel, body) in enumerate(re.findall(r"([^{}]+)\{([^{}]*)\}", css)):
        decl = parse_style(body.replace("!important", ""))
        if not decl:
            continue
        for s in sel.split(","):
            s = s.strip()
            if not s or ":" in s or "*" in s or re.search(r"\.(?:ExternalClass|ReadMsgBody|apple-|yshortcuts)", s):
                continue
            spec = (s.count("#"), s.count(".") + s.count("["), len(re.findall(r"(?:^|[\s>+~])[a-zA-Z]", s)))
            rules.append((spec, order, s, decl))
    n = 0
    styled = {}
    for spec, order, sel, decl in sorted(rules, key=lambda r: (r[0], r[1])):
        try:
            found = soup.select(sel)
        except Exception:
            continue
        for el in found:
            if el.name in SKIP_TAGS:
                continue
            styled.setdefault(id(el), (el, {}))[1].update(decl); n += 1
    for el, decl in styled.values():
        el["style"] = style_str({**decl, **parse_style(el.get("style"))})
    return n

def head_rules(soup):
    """Simple element rules (h1-h6, p, a) from <style> blocks, ignoring media queries."""
    css = " ".join(s.get_text() for s in soup.find_all("style"))
    css = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    rules = {}
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        for s in sel.split(","):
            s = s.strip()
            if re.fullmatch(r"h[1-6]|p", s):
                rules.setdefault(s, {}).update(parse_style(body.replace("!important", "")))
            if s in ("a", "a:link", "a:not([name])"):
                rules.setdefault("a", {}).update(parse_style(body.replace("!important", "")))
    return rules

def is_hidden(el):
    st = parse_style(el.get("style"))
    disp = st.get("display", "").replace("!important", "").strip()
    return disp == "none" or (st.get("max-height", "").startswith("0") and "hidden" in st.get("overflow", ""))

def kids(el):
    out = []
    for c in el.children:
        if isinstance(c, Comment):
            continue
        if isinstance(c, NavigableString):
            if c.strip():
                out.append(c)
            continue
        if c.name in SKIP_TAGS or ":" in (c.name or ""):
            continue
        out.append(c)
    return out

def bg_of(el):
    if isinstance(el, NavigableString):
        return None
    st = parse_style(el.get("style"))
    v = el.get("bgcolor") or st.get("background-color") or st.get("background")
    if not v:
        return None
    mo = re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\b(?:white|black|transparent)\b", v)
    return mo.group(0) if mo else None

def num(v):
    mo = re.match(r"\s*(\d+(?:\.\d+)?)", str(v or ""))
    return float(mo.group(1)) if mo else None

def is_pixel(img):
    w, h = num(img.get("width")), num(img.get("height"))
    st = parse_style(img.get("style"))
    w = w if w is not None else num(st.get("width"))
    h = h if h is not None else num(st.get("height"))
    return (w is not None and w <= 3) or (h is not None and h <= 3)

def real_imgs(el):
    if getattr(el, "name", None) == "img":
        return [] if is_pixel(el) else [el]
    return [i for i in el.find_all("img") if not is_pixel(i) and not any(is_hidden(a) for a in [i] + list(i.parents)[:6])]

def text_of(el):
    return (el if isinstance(el, NavigableString) else el.get_text(" ", strip=True)).strip()

def has_content(el):
    if isinstance(el, NavigableString):
        return bool(el.strip())
    if is_hidden(el):
        return False
    return bool(text_of(el) or real_imgs(el) or el.find("hr") or el.name == "hr")

def inherited(el):
    """Typography an element inherits from itself and its ancestors (nearest wins)."""
    out, crossed = {}, False
    for a in [el] + list(el.parents):
        if getattr(a, "name", None) in (None, "[document]"):
            break
        st = parse_style(a.get("style"))
        for k in TYPO_INH:
            if k in st and k not in out:
                out[k] = st[k].replace("!important", "").strip()
        # align="..." and <center> position the table below them, not the text inside a nested table
        if not crossed and "text-align" not in out and a.get("align") and a.name in ("td", "th", "div", "p"):
            out["text-align"] = a.get("align").lower()
        if not crossed and a.name == "center" and "text-align" not in out:
            out["text-align"] = "center"
        if a.name == "table":
            crossed = True
    return out

def cell_pad(el):
    """An element's padding: its style, else the table's cellpadding for a cell."""
    st = parse_style(el.get("style"))
    if el.name in ("td", "th") and not any(k.startswith("padding") for k in st):
        t = el.find_parent("table")
        if t is not None and num(t.get("cellpadding")):
            cp = f"{int(num(t.get('cellpadding')))}px"
            return {"top": cp, "right": cp, "bottom": cp, "left": cp}
    return padding_of(st)

def inner_pad(inner, el):
    """Padding of the cells strictly between an inner element (img, button cell) and el."""
    pad = dict(ZERO)
    for t in inner.parents:
        if t is el or t is None or t.name == "[document]":
            break
        if t.name in ("td", "th", "div"):
            pad = add_pad(pad, cell_pad(t))
    return pad

def chain_style(el, stop):
    """Padding and background of an element plus the ancestors it is the only content of, up to but not
    including stop (the caller adds stop's own padding with apply_pad)."""
    if el is stop:
        return dict(ZERO), None
    pad = cell_pad(el)
    bg = bg_of(el)
    cur = el
    while cur.parent is not None and cur is not stop and cur.parent is not stop:
        par = cur.parent
        if len([k for k in kids(par) if has_content(k)]) != 1 or par.name in ("body", "[document]"):
            break
        if par.name in ("td", "th", "div"):
            pp = cell_pad(par)
            pad = {k: add_px(pad[k], pp[k]) for k in pad}
        bg = bg or bg_of(par)
        cur = par
    return pad, bg

def align_of(el, cross=0):
    """Horizontal alignment of an image or button: from its own cell, not from cells above a nested table.
    cross = how many fitted (not full-width) tables to look through, e.g. a button's own table."""
    for a in [el] + list(el.parents)[:8]:
        if getattr(a, "name", None) is None:
            break
        if a.get("align") and a.name in ("td", "th", "div", "p"):
            return a.get("align").lower()
        st = parse_style(a.get("style"))
        if st.get("text-align"):
            return st["text-align"].lower()
        if (st.get("margin-left") == "auto" and st.get("margin-right") == "auto") or a.name == "center":
            return "center"
        if a.name == "table":
            if a.get("align") in ("center", "right"):
                return a.get("align")
            wide = str(a.get("width", "")).strip() == "100%" or "width:100%" in (a.get("style") or "").replace(" ", "")
            if cross and not wide:
                cross -= 1
                continue
            break
    return "left"

def img_width(img, col_px):
    w = img.get("width")
    st = parse_style(img.get("style"))
    if w and "%" not in str(w) and num(w):
        return f"{int(num(w))}px"
    for k in ("width", "max-width"):
        if st.get(k) and "%" not in st[k] and num(st[k]):
            return f"{int(num(st[k]))}px"
    return f"{int(col_px)}px"

SOCIAL = ("facebook", "instagram", "twitter", "x.com", "linkedin", "youtube", "tiktok", "pinterest", "snapchat", "threads")

def social_name(img, href):
    alt = (img.get("alt") or img.get("title") or "").strip()
    if alt:
        return alt.title()
    for s in SOCIAL:
        if s in (href or "").lower() or s in (img.get("src") or "").lower():
            return "X" if s == "x.com" else s.title()
    return "Link"

def is_button(el):
    """A short single link styled as a button (background on the link or its cell). Returns (a, bg_holder) or None."""
    if real_imgs(el):
        return None
    links = [el] if el.name == "a" else el.find_all("a")
    if len(links) != 1:
        return None
    a = links[0]
    label = text_of(a)
    if not label or len(label) > 50 or text_of(el) != label:
        return None
    if el.name != "a" and len(el.find_all(["td", "th"])) > 4:
        return None
    ast = parse_style(a.get("style"))
    if ast.get("background-color") or ast.get("background"):
        return a, a
    for depth, t in enumerate([a] + list(a.parents)):  # a background close around the link, inside el
        if depth > 4:
            break
        wide = str(t.get("width", "")).strip() == "100%" or re.search(r"(?<![-\w])width:\s*100%", t.get("style") or "")
        if bg_of(t) and not wide:
            return a, t
        if t is el:
            break
    if ast.get("border") and ast.get("padding"):
        return a, a
    return None

def button_align(a, el):
    """A button's position: set by the cell around its innermost table (or around the link if it has none)."""
    t = a.find_parent("table")
    if t is not None and (t is el or el in t.parents):
        if t.get("align") in ("center", "right", "left"):
            return t.get("align")
        return align_of(t.parent) if t.parent is not None else "left"
    return align_of(a.parent)

def button_block(el, a, holder):
    ast, hst = parse_style(a.get("style")), parse_style(holder.get("style"))
    return {"type": "button", "label": text_of(a),
            "href": a.get("href", ""), "align": button_align(a, el),
            "bg": bg_of(holder) or "#000000",
            "color": ast.get("color") or hst.get("color") or "#ffffff",
            "font_family": ast.get("font-family") or hst.get("font-family") or inherited(a).get("font-family") or "Arial, sans-serif",
            "font_size": ast.get("font-size") or hst.get("font-size") or "16px",
            "font_weight": ast.get("font-weight") or hst.get("font-weight") or "400",
            "radius": ast.get("border-radius") or hst.get("border-radius") or "0px",
            "inner_padding": padding_of(ast) if any(k.startswith("padding") for k in ast)
            else (padding_of(hst) if any(k.startswith("padding") for k in hst) else {"top": "12px", "right": "24px", "bottom": "12px", "left": "24px"}),
            "letter_spacing": ast.get("letter-spacing", "0px"),
            "border_bottom": ast.get("border-bottom") or hst.get("border-bottom")}

ZERO = {"top": "0px", "right": "0px", "bottom": "0px", "left": "0px"}

def add_pad(a, b):
    return {k: add_px(a[k], b[k]) for k in ZERO}

def apply_pad(blocks, pad):
    """Add a container's padding to its blocks: sides to all, top to the first, bottom to the last.
    Spacers take no side padding."""
    if not blocks or all(css_px(v) == 0 for v in pad.values()):
        return blocks
    for i, b in enumerate(blocks):
        p = dict(b["padding"])
        p["left"], p["right"] = add_px(p["left"], pad["left"]), add_px(p["right"], pad["right"])
        if i == 0: p["top"] = add_px(p["top"], pad["top"])
        if i == len(blocks) - 1: p["bottom"] = add_px(p["bottom"], pad["bottom"])
        if b["type"] == "spacer":
            b["height"] = add_px(b["height"], add_px(p["top"], p["bottom"]) if len(blocks) == 1 else "0px")
            p = dict(ZERO)
        b["padding"] = p
    return blocks

class Parser:
    def __init__(self, width, warnings):
        self.W, self.warnings = width, warnings

    def block(self, el, stop, col_px, **kw):
        pad, bg = chain_style(el, stop) if not isinstance(el, NavigableString) else ({"top": "0px", "right": "0px", "bottom": "0px", "left": "0px"}, None)
        return {"visibility": "all", "padding": pad, "background": bg, **kw}

    def classify(self, el, stop, col_px):
        """List of blocks for el, or None to look inside it."""
        if isinstance(el, NavigableString):
            return [self.block(el, stop, col_px, type="text", wrapper_style=inherited(el.parent), html=str(el).strip())]
        if is_hidden(el):
            return []
        imgs = real_imgs(el)
        txt = text_of(el)
        if el.name == "hr" or (not txt and not imgs and re.search(r"border-(?:top|bottom)\s*:\s*\d", el.get("style") or "")
                               and not el.find("table")):
            st = parse_style(el.get("style"))
            border = st.get("border-top") or st.get("border-bottom") or "1px solid #BBBBBB"
            if el.name == "hr" and not (st.get("border-top") or st.get("border-bottom")):
                border = f"1px solid {st.get('border-color') or st.get('color') or el.get('color') or '#BBBBBB'}"
            return [self.block(el, stop, col_px, type="divider", border=border, width=st.get("width", "100%"))]
        if not txt and not imgs and el.find("hr"):
            hr = el.find("hr")
            st = parse_style(hr.get("style"))
            border = st.get("border-top") or st.get("border-bottom") or f"1px solid {st.get('border-color') or hr.get('color') or '#BBBBBB'}"
            b = self.block(el, stop, col_px, type="divider", border=border, width=st.get("width", "100%"))
            b["padding"] = add_pad(b["padding"], inner_pad(hr, el))
            return [b]
        if not txt and not imgs:
            h = num(el.get("height")) or num(parse_style(el.get("style")).get("height")) or num(parse_style(el.get("style")).get("line-height"))
            if h and h >= 4 and el.name in ("td", "th", "div", "p", "tr", "table"):
                return [{"visibility": "all", "padding": {"top": "0px", "right": "0px", "bottom": "0px", "left": "0px"},
                         "background": bg_of(el), "type": "spacer", "height": f"{int(h)}px"}]
            return []
        btn = is_button(el)
        if btn:
            b = self.block(el, stop, col_px, **button_block(el, *btn))
            if btn[1] is not el:
                b["padding"] = add_pad(b["padding"], inner_pad(btn[1], el))
            return [b]
        if len(imgs) >= 2 and len(txt) <= 40:
            small = [i for i in imgs if (num(i.get("width")) or num(parse_style(i.get("style")).get("width")) or 99) <= 64]
            if len(small) == len(imgs) and all(i.find_parent("a") for i in imgs) and not el.find(["h1", "h2", "h3"]):
                icons = []
                for i in imgs:
                    href = i.find_parent("a").get("href", "")
                    name = social_name(i, href)
                    if not href:
                        self.warnings.append(f"Social icon '{name}' has no link in the source")
                    icons.append({"name": name, "href": href, "src": i.get("src", ""), "width": img_width(i, 32)})
                b = self.block(el, stop, col_px, type="social", icons=icons)
                b["padding"] = add_pad(b["padding"], inner_pad(imgs[0].find_parent("a"), el))
                return [b]
        if len(imgs) == 1 and not txt:
            img = imgs[0]
            a = img.find_parent("a")
            src = img.get("src", "")
            if not src:
                self.warnings.append("Image with no source in the export (unfinished template)")
            b = self.block(el, stop, col_px, type="image", src=src, alt=(img.get("alt") or "").strip(),
                           href=a.get("href", "") if a is not None else "", width=img_width(img, col_px),
                           align=align_of(img.parent if img.parent is not None else img))
            if img is not el:
                b["padding"] = add_pad(b["padding"], inner_pad(img, el))
            return [b]
        if el.name in ("div", "td", "th", "center", "section"):
            only = [k for k in kids(el) if has_content(k)]
            if len(only) == 1 and not isinstance(only[0], NavigableString) and only[0].name in ("div", "td", "th", "table", "center", "section"):
                return None  # a wrapper: look inside, so its padding is counted and the text keeps no wrapper divs
        if not imgs and not el.find(["table", "img"]):
            if el.name in TEXT_BLOCK or el.name in INLINE:
                html = str(el)
                wst = inherited(el.parent) if el.parent is not None else {}
            else:
                html = el.decode_contents()
                wst = inherited(el)
            if el.name not in TEXT_BLOCK and el.name not in INLINE and el.name not in ("td", "th", "div", "center", "span", "font"):
                return None
            return [self.block(el, stop, col_px, type="text", wrapper_style=wst, html=html.strip())]
        return None

    def flat(self, el, stop, col_px):
        """All blocks inside a column, in reading order (nested layout is stacked)."""
        got = self.classify(el, stop, col_px)
        if got is not None:
            return got
        out, buf = [], []
        def flush():
            if buf and any(text_of(b) for b in buf):
                html = "".join(str(b) for b in buf).strip()
                out.append({"visibility": "all", "padding": {"top": "0px", "right": "0px", "bottom": "0px", "left": "0px"},
                            "background": None, "type": "text", "wrapper_style": inherited(el), "html": f"<p>{html}</p>"})
            buf.clear()
        for ch in kids(el):
            if isinstance(ch, NavigableString) or (ch.name in INLINE and not real_imgs(ch) and not is_button(ch)):
                buf.append(ch); continue
            flush()
            out += self.flat(ch, stop, col_px)
        flush()
        if el is not stop and el.name in ("td", "th", "div") and len(out) >= 2:
            out = apply_pad(out, cell_pad(el))  # a padded cell around several blocks (single children are counted by chain_style)
        multi = [tr for tr in el.find_all("tr") if len([c for c in kids(tr) if getattr(c, "name", None) in ("td", "th") and has_content(c)]) >= 2]
        if multi and stop is not None and stop.name in ("td", "th") and el is stop:
            self.warnings.append("A column holds its own side-by-side layout; it was stacked vertically: " + text_of(el)[:60])
        return out

    def col_pct(self, cells, parent_w):
        raw = []
        for c in cells:
            w = c.get("width") or parse_style(c.get("style")).get("width") or parse_style(c.get("style")).get("max-width")
            if w and "%" in str(w):
                raw.append(num(w))
            elif num(w):
                raw.append(num(w) / parent_w * 100)
            else:
                raw.append(None)
        known = [r for r in raw if r]
        rest = max(0.0, 100 - sum(known))
        missing = raw.count(None)
        raw = [r if r else (rest / missing if missing else 0) for r in raw]
        tot = sum(raw) or 1
        return [r * 100 / tot for r in raw]

    def is_container(self, el):
        st = parse_style(el.get("style"))
        return el.name in ("table", "div", "td") and any(num(v) == self.W and "%" not in str(v)
                                                        for v in (el.get("width"), st.get("width"), st.get("max-width")) if v)

    def content_cells(self, el):
        """For a table/tr: the content cells of its single row that has 2+ of them, else None."""
        trs = [el] if el.name == "tr" else [t for t in el.find_all("tr") if t.find_parent("table") is el]
        rows = [[c for c in kids(tr) if getattr(c, "name", None) in ("td", "th") and has_content(c)] for tr in trs]
        if el.name == "tr" and len(rows[0]) >= 2:
            return rows[0]
        if el.name == "table" and len(rows) == 1 and len(rows[0]) >= 2:
            return rows[0]
        return None

    def rows(self, el, bg, pad=None):
        """Rows for el. pad is the padding of the single-child containers above el, passed down so it isn't lost."""
        pad = pad or ZERO
        if not isinstance(el, NavigableString) and self.is_container(el) and any(css_px(v) for v in pad.values()):
            # padding outside the content-width container is page margin: keep its height as spacer rows
            spacer = lambda h: {"background": "transparent", "columns": [{"pct": 100.0, "blocks": [
                {"visibility": "all", "padding": dict(ZERO), "background": None, "type": "spacer", "height": h}]}]}
            top, bottom = pad["top"], pad["bottom"]
            inner = self.rows(el, bg, None)
            return ([spacer(top)] if css_px(top) else []) + inner + ([spacer(bottom)] if css_px(bottom) else [])
        if isinstance(el, NavigableString):
            return [{"background": bg, "columns": [{"pct": 100.0, "blocks": apply_pad(self.flat(el, None, self.W), pad)}]}]
        if is_hidden(el):
            return []
        bg = bg_of(el) or bg
        btn = is_button(el)
        if btn or (len(real_imgs(el)) == 1 and not text_of(el)):
            inner = btn[1] if btn else real_imgs(el)[0]
            for t in inner.parents:  # a section background between el and the image/button is the row's
                if t is el or t is None:
                    break
                if btn and text_of(t) == text_of(btn[0]) and len(t.find_all(["td", "th"])) <= 3:
                    continue  # part of the button itself
                bg = bg_of(t) or bg if t.name in ("td", "th", "div", "table", "tr") else bg
            return [{"background": bg, "columns": [{"pct": 100.0, "blocks": apply_pad(self.flat(el, el, self.W), add_pad(pad, cell_pad(el)))}]}]
        cells = self.content_cells(el) if el.name in ("tr", "table") else None
        if cells is None and el.name in ("div", "section", "td", "th") and len([k for k in kids(el) if has_content(k)]) >= 2:
            inl = [k for k in kids(el) if not isinstance(k, NavigableString) and "inline-block" in (k.get("style") or "")]
            if len(inl) >= 2 and all(has_content(k) for k in inl):
                cells = inl  # hybrid/fluid columns: inline-block divs side by side
        if cells:
            pcts = self.col_pct(cells, self.W)
            cols = [{"pct": p, "blocks": apply_pad(self.flat(c, c, self.W * p / 100), cell_pad(c)), "background": bg_of(c)}
                    for c, p in zip(cells, pcts)]
            if len(cols) > 4:
                self.warnings.append(f"A row with {len(cols)} columns was kept as one column of stacked blocks")
                cols = [{"pct": 100.0, "blocks": [b for c in cols for b in c["blocks"]]}]
            return [{"background": bg, "columns": cols}]
        sections = [d for d in el.find_all(["div", "section"]) if bg_of(d) and has_content(d)]
        if el.name in TEXT_BLOCK or (el.name not in ("table", "tbody", "thead", "tfoot", "tr") and not el.find("table") and not sections):
            blocks = self.flat(el, el, self.W)
            if el.name in ("td", "th", "div"):
                blocks = apply_pad(blocks, cell_pad(el))
            return [{"background": bg, "columns": [{"pct": 100.0, "blocks": apply_pad(blocks, pad)}]}] if blocks else []
        content = [k for k in kids(el) if has_content(k) or (not isinstance(k, NavigableString) and k.name in ("td", "tr", "tbody", "table"))]
        own = cell_pad(el) if el.name in ("td", "th", "div") else ZERO
        inner = add_pad(pad, own)
        if self.is_container(el):
            inner = dict(ZERO)  # padding outside the content-width container is page margin, not block spacing
        out = []
        for i, ch in enumerate(content):
            p = dict(inner)
            if i > 0: p["top"] = "0px"
            if i < len(content) - 1: p["bottom"] = "0px"
            out += self.rows(ch, bg, p)
        return out

def analyze(path, out_dir, esp_arg=None):
    raw = open(path, encoding="utf-8", errors="replace").read()
    # HTML comments (Outlook conditionals included: ghost tables and VML buttons) and <title> aren't carried over;
    # drop them first so their tokens aren't listed for mapping. Content between <!--[if !mso]><!--> and
    # <!--<![endif]--> is ordinary HTML and stays.
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    raw = re.sub(r"<title>.*?</title>", "", raw, flags=re.S | re.I)
    esp, signals = detect_esp(raw)
    if esp_arg:
        esp = esp_arg
    tokens, index = [], {}
    work = tokenize(raw, esp, tokens, index)
    soup = BeautifulSoup(work, "html.parser")
    warnings = []
    css_rules = inline_css(soup)
    rules = head_rules(soup)
    if not any(k.startswith("margin") for k in rules.get("p", {})):
        # the export relies on the browser's default paragraph spacing; the Visual Builder's default is none
        rules.setdefault("p", {}).update({"margin-top": "1em", "margin-bottom": "1em"})
    body = soup.body or soup
    bst = parse_style(body.get("style") if body is not soup else "")

    # content width = most common table width / max-width between 320 and 900 px
    widths = [int(w) for w in re.findall(r'<table[^>]*\swidth="(\d{3})"', work)]
    widths += [int(w) for w in re.findall(r'style="[^"]*?(?<![-\w])(?:max-)?width:\s*(\d{3})px', work)]
    widths = [w for w in widths if 320 <= w <= 900]
    width = max(set(widths), key=widths.count) if widths else 600

    body_bg = (body.get("bgcolor") if body is not soup else None) or bst.get("background-color") or bst.get("background")
    if not body_bg:
        outer = soup.find(lambda t: t.name in ("table", "td", "div", "center") and bg_of(t)
                          and (t.get("width") in ("100%",) or "100%" in (t.get("style") or "")))
        body_bg = bg_of(outer) if outer is not None else "#ffffff"
    body_bg = bg_of(soup.new_tag("x", attrs={"style": f"background-color:{body_bg}"})) or "#ffffff"

    # preheader: first hidden element with text
    preheader, pre_raw = "", ""
    for el in body.find_all(True):
        if is_hidden(el) and text_of(el):
            pre_raw = text_of(el)
            preheader = restore(re.sub(r"[͏‌  ​\s]+", " ", text_of(el)).strip(), tokens)
            break
    hidden_dropped = sum(1 for el in body.find_all(True) if is_hidden(el) and not any(is_hidden(p) for p in el.parents if p.name))

    rows = Parser(width, warnings).rows(body, None)
    # drop empty rows; a row background equal to the page background is transparent
    clean = []
    for r in rows:
        r["columns"] = [c for c in r["columns"] if c["blocks"]] or []
        if not r["columns"]:
            continue
        if not r["background"] or r["background"].lower() == body_bg.lower():
            r["background"] = "transparent"
        tot = sum(c["pct"] for c in r["columns"]) or 100
        for c in r["columns"]:
            c["pct"] = round(c["pct"] * 100 / tot, 2)
        # merge into the previous row when both are single-column with the same background
        if clean and len(r["columns"]) == 1 and len(clean[-1]["columns"]) == 1 and clean[-1]["background"] == r["background"]:
            clean[-1]["columns"][0]["blocks"] += r["columns"][0]["blocks"]
        else:
            clean.append(r)
    rows = clean

    fonts_all = re.findall(r"font-family:\s*([^;\"]+)", work)
    default_font = rules.get("p", {}).get("font-family") or (max(set(fonts_all), key=fonts_all.count).strip() if fonts_all else "Arial, sans-serif")
    link_colors = [parse_style(a.get("style")).get("color") for a in soup.find_all("a") if parse_style(a.get("style")).get("color")]
    link_color = rules.get("a", {}).get("color") or (max(set(link_colors), key=link_colors.count) if link_colors else "#0000EE")

    model_json = json.dumps(rows, ensure_ascii=False)
    model = {"source": path, "esp": esp, "width": width, "body_background": body_bg, "link_color": link_color,
             "head_rules": rules, "rows": rows, "default_font": default_font, "tokens": tokens, "preheader_in_source": preheader}
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "model.json"), "w", encoding="utf-8") as fh:
        json.dump(model, fh, indent=1, ensure_ascii=False)

    # ---------------- report
    tr = Translator({}, tokens, esp, dry_run=True)
    tok_report, spans, outside = [], [], []
    for i, src in enumerate(tokens):
        tr.unconfirmed = False
        auto = tr.describe(src)
        placed = (PH % i) in model_json or (PH % i) in pre_raw
        tok_report.append({"token": src if len(src) <= 300 else src[:300] + "…", "count": raw.count(src),
                           "control_flow": bool(CONTROL_SRC.search(src.strip())), "auto": auto,
                           "needs_mapping": auto is None,
                           "field_to_confirm": auto is not None and tr.unconfirmed})
        if not placed:
            outside.append(src[:80])
    for ri, r in enumerate(rows):
        for ci, c in enumerate(r["columns"]):
            for b in c["blocks"]:
                srcs = [tokens[int(n)] for n in PH_RE.findall(json.dumps(b, ensure_ascii=False))]
                opens = sum(1 for s in srcs if re.match(r"\{%\s*(?:if|for|unless|case)\b|\{\{#|\*\|IF(?:NOT)?:", s, re.I))
                closes = sum(1 for s in srcs if re.match(r"\{%\s*end\w+|\{\{/|\*\|END:", s, re.I))
                if opens != closes:
                    spans.append(f"row {ri} col {ci}: a {b['type']} block opens {opens} and closes {closes} conditions/loops")
    imgs = sorted({restore(i.get("src", ""), tokens) for i in real_imgs(soup)} |
                  {restore(u, tokens) for u in re.findall(r"background(?:-image)?\s*[:=]\s*[\"']?(?:url\()?['\"]?(https?://[^\"')\s]+)", work)})
    imgs = [u for u in imgs if u.startswith("http")]
    hosts = {}
    for u in imgs:
        h = re.sub(r"^https?://([^/]+).*", r"\1", u)
        hosts[h] = hosts.get(h, 0) + 1
    links = [a.get("href", "") for a in soup.find_all("a")]
    dead = sum(1 for h in links if not h.strip() or h.strip() == "#")
    plain = restore(soup.get_text(" ", strip=True), tokens)
    codes = sorted(set(re.findall(r"\b(?:code|coupon|promo)\b[^A-Za-z0-9]{0,20}([A-Z0-9][A-Z0-9_-]{3,})", plain, re.I)))
    if any(b.get("background") for r in rows for c in r["columns"] for b in c["blocks"]) or re.search(r"background-image|background=\"http", work):
        if re.search(r"background-image|background=\"http", work):
            warnings.append("The export uses background images; the Visual Builder can't show those in rows built this way. "
                            "They are dropped; re-add them in the Visual Builder if needed")
    report = {
        "esp_guess": esp,
        "esp_signals": signals,
        "recommended_skill": "convert-klaviyo-email-to-bloomreach" if esp == "klaviyo" else None,
        "rows": len(rows),
        "blocks": sum(len(c["blocks"]) for r in rows for c in r["columns"]),
        "block_types": {t: n for t, n in sorted(
            {b["type"]: sum(1 for r2 in rows for c2 in r2["columns"] for b2 in c2["blocks"] if b2["type"] == b["type"])
             for r in rows for c in r["columns"] for b in c["blocks"]}.items())},
        "custom_html_blocks": sum(1 for r in rows for c in r["columns"] for b in c["blocks"] if b["type"] == "html"),
        "width_px": width,
        "tokens": tok_report,
        "tokens_needing_mapping": sum(1 for t in tok_report if t["needs_mapping"]),
        "tokens_lost_in_layout": outside,
        "control_flow_split_across_blocks": spans,
        "uses_event_data": any(re.search(r"\bevent\b|\$\{?event_properties|\bevent_properties\b", t, re.I) for t in tokens),
        "preheader_in_source": preheader,
        "images_total": len(imgs),
        "image_hosts": hosts,
        "images_on_esp_cdn": [u for u in imgs if ESP_CDN.search(u)],
        "empty_or_hash_links": dead,
        "head_css_rules_inlined": css_rules,
        "hidden_elements_dropped": hidden_dropped,
        "fonts_used": sorted(set(f.split(",")[0].strip(" '\"") for f in fonts_all)),
        "hardcoded_codes": codes,
        "placeholder_copy": bool(re.search(r"lorem ipsum|\bHEADLINE\b|ADD YOUR CTA|Product Title|Your text here", plain, re.I)),
        "warnings": sorted(set(warnings)),
    }
    print(json.dumps(report, indent=1, ensure_ascii=False))

# ----------------------------------------------------------------------------------------------
# TRANSLATE: source template tokens -> Bloomreach Jinja
# ----------------------------------------------------------------------------------------------
# Fallbacks for customer properties printed without a default (Bloomreach prints None for an empty one).
# mapping.fallbacks overrides these per property; anything else falls back to ''.
DEFAULT_FALLBACKS = {"first_name": "there"}

# Standard fields every ESP has, under the names each ESP uses. Values are mapping.customer_properties keys.
STANDARD = {"first_name": "first_name", "firstname": "first_name", "fname": "first_name", "first name": "first_name",
            "last_name": "last_name", "lastname": "last_name", "lname": "last_name", "last name": "last_name",
            "email": "email", "email_address": "email", "emailaddress": "email", "emailaddr": "email",
            "phone": "phone", "phone_number": "phone", "phonenumber": "phone", "mobile": "phone"}

MC_SYSTEM = {"REWARDS", "MC_PREVIEW_TEXT", "ARCHIVE_PAGE", "ARCHIVE", "MC_LANGUAGE", "IS_FB_PAGE", "LIST:COMPANY"}


class Translator:
    def __init__(self, mapping, tokens, esp, dry_run=False):
        self.m, self.tokens, self.esp, self.dry = mapping, tokens, esp, dry_run
        self.log, self.errors, self.warnings = {}, [], []
        self.cache = {}
        self.unconfirmed = False
        self.untranslated = []

    def note(self, rule, n=1):
        if n:
            self.log[rule] = self.log.get(rule, 0) + n

    # --- building blocks ------------------------------------------------------------------
    def prop(self, name):
        """Source field name -> Bloomreach customer expression (no braces)."""
        std = self.m.get("customer_properties", {})
        custom = self.m.get("custom_properties", {})
        key = STANDARD.get(name.strip().lower())
        if name in custom:
            p = custom[name]
        elif key and key in std:
            p = std[key]
        elif key:
            p = key
        else:
            p = name
            self.unconfirmed = True
            if not self.dry:
                self.warnings.append(f"Source field '{name}' has no confirmed Bloomreach mapping; used customer['{p}'] as-is "
                                     "(add it to mapping.custom_properties)")
        if p is None:
            if not self.dry:
                self.warnings.append(f"Source field '{name}' does not exist in the project; replaced with an empty value")
            return "''"
        return f"customer.{p}" if re.fullmatch(r"[A-Za-z_]\w*", p) else f"customer['{p}']"

    def unsub(self):
        return self.m.get("unsubscribe_token", "{{ consent.page }}")

    def org(self, key):
        val = self.m.get("organization", {}).get(key)
        if val:
            return val
        if self.dry:
            return f"[company {key.replace('_', ' ')} from mapping.organization.{key}]"
        if not self.dry:
            self.errors.append(f"The source uses the company {key.replace('_', ' ')}, but mapping.organization.{key} is empty "
                               "(set a project variable or a literal)")
        return f"<!-- TODO: company {key.replace('_', ' ')} -->"

    def liquid_expr(self, e):
        """Liquid / Handlebars-ish expression -> Jinja expression, or None if anything is left unknown."""
        e = e.strip()
        e = re.sub(r"custom_attribute\.\$\{([^}]+)\}", lambda mo: self.prop(mo.group(1)), e)
        e = re.sub(r"\$\{([^}]+)\}", lambda mo: self.prop(mo.group(1)), e)
        e = re.sub(r"\bcontact\.(\w+)", lambda mo: self.prop(mo.group(1)), e)
        e = re.sub(r"\|\s*default\s*:\s*(['\"])(.*?)\1", r"| default(\1\2\1, true)", e)
        e = re.sub(r"\|\s*default\(\s*((['\"]).*?\2)\s*\)", r"| default(\1, true)", e)
        e = re.sub(r"\|\s*upcase\b", "| upper", e)
        e = re.sub(r"\|\s*downcase\b", "| lower", e)
        e = re.sub(r"\|\s*strip\b", "| trim", e)
        e = re.sub(r"\|\s*truncate\s*:\s*(\d+)", r"| truncate(\1)", e)
        e = re.sub(r"\s*!=\s*(?:blank|empty|nil|null)\b", "", e)
        e = re.sub(r"^(.*?)\s*==\s*(?:blank|empty|nil|null)\b", r"not \1", e)
        if re.search(r"\$\{|\|\s*\w+\s*:|\bnil\b|\bblank\b", e):
            return None
        return e

    def describe(self, src):
        """Short description of the automatic translation, or None if the token needs mapping.tokens."""
        out = self.known(src)
        return None if out is None else out

    # --- the rules --------------------------------------------------------------------------
    def known(self, src):
        s = src.strip()
        # Mailchimp *|TAG|*
        mo = re.fullmatch(r"\*\|(.+?)\|\*", s, re.S)
        if mo:
            t = mo.group(1).strip()
            T = t.upper()
            if T in ("UNSUB",):
                return self.unsub()
            if T in ("UPDATE_PROFILE", "UPDATE_PROFILE_LINK", "EMAIL_PREFERENCES"):
                return self.unsub()
            if T in ("ARCHIVE", "ARCHIVE_LINK_SHORT"):
                return "{{ email.view }}"
            if T in ("LIST:COMPANY", "COMPANY"):
                return self.org("name")
            if T in ("LIST:ADDRESS", "HTML:LIST_ADDRESS_HTML", "LIST_ADDRESS", "LIST:ADDRESSLINE", "HTML:LIST_ADDRESS"):
                return self.org("full_address")
            if T in ("LIST:URL",):
                return self.org("url")
            if T in ("CURRENT_YEAR", "DATE:Y"):
                return "{{ sent_timestamp | from_timestamp('%Y') }}"
            if T in ("MC_PREVIEW_TEXT", "REWARDS", "HTML:REWARDS", "REWARDS_TEXT", "MC:TRANSLATE", "LIST:DESCRIPTION", "ABOUT_LIST",
                     "MC_LANGUAGE_LABEL", "MC:TOC", "LIST:RECIPIENTS", "LIST:SUBSCRIBERS"):
                return ""
            if T in ("MC:SUBJECT",):
                return getattr(self, "subject", None) or "[the subject from meta.json]"
            if T in ("ELSE:",):
                return "{% else %}"
            if T in ("END:IF",):
                return "{% endif %}"
            mo2 = re.fullmatch(r"(IF|IFNOT|ELSEIF):([A-Z0-9_]+)(?:\s*(=|!=|>|<|>=|<=)\s*(.+))?", t, re.I)
            if mo2 and mo2.group(2).upper() in MC_SYSTEM:
                # conditions on Mailchimp's own features (rewards badge, preview text, archive) have no Bloomreach
                # equivalent: the IF branch never shows, the IFNOT branch always does
                kw = mo2.group(1).upper()
                return "{%% %s %s %%}" % ("elif" if kw == "ELSEIF" else "if", "true" if kw == "IFNOT" else "false")
            if mo2:
                kw, field, op, val = mo2.group(1).upper(), mo2.group(2), mo2.group(3), mo2.group(4)
                expr = self.prop(field)
                if op:
                    val = val.strip()
                    val = val if re.fullmatch(r"-?\d+(\.\d+)?", val) else "'" + val.strip("'\"").replace("'", "\\'") + "'"
                    expr = f"{expr} {'==' if op == '=' else op} {val}"
                if kw == "IFNOT":
                    expr = f"not ({expr})" if op else f"not {expr}"
                return "{%% %s %s %%}" % ("elif" if kw == "ELSEIF" else "if", expr)
            if re.fullmatch(r"[A-Z][A-Z0-9_]{0,30}", T) and T not in ("FACEBOOK:LIKE", "TWITTER:TWEET"):
                return "{{ %s }}" % self.prop(t if T not in ("FNAME", "LNAME", "EMAIL", "PHONE") else t.lower())
            return None
        # SFMC
        if s.startswith("%%[") or s.startswith("%%="):
            mo = re.fullmatch(r"%%=\s*AttributeValue\(\s*['\"]([^'\"]+)['\"]\s*\)\s*=%%", s, re.I)
            if mo:
                return "{{ %s }}" % self.prop(mo.group(1))
            mo = re.fullmatch(r"%%=\s*v\(\s*\[?([A-Za-z_][\w ]*?)\]?\s*\)\s*=%%", s, re.I)
            if mo and not mo.group(1).startswith("@"):
                return "{{ %s }}" % self.prop(mo.group(1))
            return None  # AMPscript logic and @variables need a mapping
        mo = re.fullmatch(r"%%([A-Za-z_][\w-]*)%%", s)
        if mo:
            n = mo.group(1).lower()
            if n in ("unsub_center_url", "unsubscribe_url", "subscription_center_url", "profile_center_url", "unsub_url"):
                return self.unsub()
            if n in ("view_email_url", "viewemailurl"):
                return "{{ email.view }}"
            if n in ("member_busname",):
                return self.org("name")
            if n in ("member_addr",):
                return self.org("full_address")
            if n in ("member_city", "member_state", "member_postalcode", "member_country"):
                if not self.dry:
                    self.note("SFMC address part (city/state/postcode/country) -> dropped; mapping.organization.full_address holds the whole address")
                return ""
            if n in ("xtyear",):
                return "{{ sent_timestamp | from_timestamp('%Y') }}"
            if n in ("emailaddr", "emailaddress", "email", "firstname", "first_name", "lastname", "last_name", "subscriberkey"):
                if n == "subscriberkey":
                    return None
                return "{{ %s }}" % self.prop(n)
            if n.startswith(("xt", "_", "jobid", "listid", "member_", "subscriberid", "emailname_")):
                return None
            return "{{ %s }}" % self.prop(mo.group(1))
        # ActiveCampaign
        mo = re.fullmatch(r"%([A-Z][A-Z0-9_-]+)%", s)
        if mo:
            n = mo.group(1)
            if n in ("UNSUBSCRIBELINK",):
                return self.unsub()
            if n in ("UPDATELINK",):
                return self.unsub()
            if n in ("WEBCOPY",):
                return "{{ email.view }}"
            if n.startswith("SENDER-INFO"):
                return self.org("name") + (", " if "SINGLELINE" in n else "<br>") + self.org("full_address")
            if n in ("FULLNAME",):
                return "{{ %s }} {{ %s }}" % (self.prop("first_name"), self.prop("last_name"))
            return "{{ %s }}" % self.prop(n.lower().replace("-", "_"))
        # Handlebars (Iterable)
        if s.startswith("{{{"):
            inner = s[3:-3].strip()
            return "{{ %s }}" % self.prop(inner) if re.fullmatch(r"[A-Za-z_]\w*", inner) else None
        if s.startswith("{{"):
            inner = s[2:-2].strip()
            if inner in ("unsubscribeUrl", "unsubscribeMessageTypeUrl", "hostedUnsubscribeUrl", "unsubscribe_link",
                         "unsubscribe_link_all", "${set_user_to_unsubscribed_url}", "${email_unsubscribe_url}"):
                return self.unsub()
            if inner in ("viewInBrowserUrl", "view_as_page_url", "web_version_url"):
                return "{{ email.view }}"
            if inner == "else":
                return "{% else %}"
            if inner in ("/if", "/unless"):
                return "{% endif %}"
            mo = re.fullmatch(r"#(if|unless)\s+([A-Za-z_][\w.]*)", inner)
            if mo:
                e = self.prop(mo.group(2))
                return "{%% if %s%s %%}" % ("not " if mo.group(1) == "unless" else "", e)
            mo = re.fullmatch(r"defaultIfEmpty\s+([A-Za-z_]\w*)\s+(['\"])(.*?)\2", inner)
            if mo:
                return "{{ %s | default(%s, true) }}" % (self.prop(mo.group(1)), repr(mo.group(3)))
            if inner.startswith(("#", "/", ">", "!")):
                return None  # each / with / partials / comments
            if inner.startswith("site_settings."):
                k = inner.split(".", 1)[1]
                if k in ("company_name",):
                    return self.org("name")
                if k in ("company_street_address_1",):
                    return self.org("full_address")
                if k.startswith(("company_street_address_2", "company_city", "company_state", "company_zip", "company_country")):
                    if not self.dry:
                        self.note("HubSpot company address part -> dropped; mapping.organization.full_address holds the whole address")
                    return ""
                if k in ("company_domain", "company_url"):
                    return self.org("url")
                return None
            if re.fullmatch(r"local_dt\s*\|\s*datetimeformat\(\s*['\"]%Y['\"]\s*\)|year", inner):
                return "{{ sent_timestamp | from_timestamp('%Y') }}"
            if self.esp == "iterable" and re.fullmatch(r"[A-Za-z_]\w*", inner) and inner not in ("customer", "event", "item", "product"):
                return "{{ %s }}" % self.prop(inner)
            if re.fullmatch(r"(?:first_name|last_name|email|firstname|lastname|FNAME)", inner):
                return "{{ %s }}" % self.prop(inner)
            if re.search(r"\$\{|\bcontact\.|custom_attribute\.", inner):
                e = self.liquid_expr(inner)
                return None if e is None else "{{ %s }}" % e
            if re.match(r"(customer|event|catalogs|aggregates|recommendations|vouchers|project_variables|consent|email)\b", inner) and self.esp in ("jinja-like", "plain"):
                return s  # already Bloomreach-style; kept as is
            return None
        if s.startswith("{%"):
            inner = s[2:-2].strip().strip("-").strip()
            if inner in ("else", "endif", "endfor"):
                return "{%% %s %%}" % inner
            if inner == "endunless":
                return "{% endif %}"
            mo = re.fullmatch(r"(if|elsif|elif|unless)\s+(.+)", inner, re.S)
            if mo and re.search(r"\$\{|\bcontact\.|custom_attribute\.", mo.group(2)):
                e = self.liquid_expr(mo.group(2))
                if e is None:
                    return None
                kw = {"elsif": "elif", "unless": "if"}.get(mo.group(1), mo.group(1))
                return "{%% %s %s %%}" % (kw, f"not ({e})" if mo.group(1) == "unless" else e)
            return None
        return None

    # --- apply ------------------------------------------------------------------------------
    def token(self, i):
        if i in self.cache:
            return self.cache[i]
        src = self.tokens[i]
        mt = self.m.get("tokens", {})
        norm = re.sub(r"\s+", " ", src.strip())
        hit = src if src in mt else next((k for k in mt if re.sub(r"\s+", " ", k.strip()) == norm), None)
        if hit is not None:
            out = mt[hit] if mt[hit] is not None else ""
            self.note("mapping.tokens: " + (norm[:60] + "…" if len(norm) > 60 else norm))
        else:
            out = self.known(src)
            if out is None:
                self.errors.append(f"No translation for source token {norm[:120]!r}: add it to mapping.tokens")
                self.untranslated.append(src)
                out = src
            else:
                self.note("auto: " + (norm[:50] + "…" if len(norm) > 50 else norm) + " -> " + (out[:60] or "''"))
        self.cache[i] = out
        return out

    def add_fallback(self, mo):
        expr, rest = mo.group(1), mo.group(2).strip()
        if "default(" in rest:
            return mo.group(0)
        prop = re.sub(r"^customer(?:\.|\[')|'\]$", "", expr)
        fb = self.m.get("fallbacks", {}).get(prop, DEFAULT_FALLBACKS.get(prop, ""))
        self.note(f"{{{{ customer.{prop} }}}} with no fallback -> default({fb!r}, true)")
        quoted = "'" + str(fb).replace("\\", "\\\\").replace("'", "\\'") + "'"
        return "{{ %s | default(%s, true)%s }}" % (expr, quoted, " " + rest if rest else "")

    def translate(self, html):
        h = PH_RE.sub(lambda mo: self.token(int(mo.group(1))), html or "")
        # Most ESPs print an empty field as nothing; Bloomreach prints None. Give every customer property
        # printed without a default one: mapping.fallbacks, else DEFAULT_FALLBACKS, else ''.
        h = re.sub(r"\{\{\s*(customer(?:\.\w+|\['[^']*'\]))\s*((?:\|[^}]*)?)\}\}", self.add_fallback, h)
        return h

    def translate_raw(self, text):
        """Translate a string that still holds source syntax (subject, preheader from meta.json)."""
        idx = {s: i for i, s in enumerate(self.tokens)}
        return self.translate(tokenize(text or "", self.esp, self.tokens, idx))

LEFTOVER = [(r"\*\|[^|*]{1,120}\|\*", "Untranslated Mailchimp merge tag"), (r"%%[\[=]?[^%]{1,200}?[\]=]?%%", "Untranslated SFMC syntax"),
            (r"\$\{[^}]*\}", "Untranslated Braze/Liquid attribute"), (r"\{\{[#/^>]|\{\{\{", "Untranslated Handlebars block"),
            (r"\{\{\s*contact\.|\{\{\s*person\.|\bsite_settings\.", "Untranslated HubSpot/Klaviyo reference"),
            (r"\|\s*\w+\s*:\s*['\"\w]", "Liquid/Django-style filter argument (use filter(arg))"),
            (r"\{\{\s*voucher\(", "Invalid voucher syntax (use vouchers['pool'].assign_available())")]

# ----------------------------------------------------------------------------------------------
# BUILD: model -> BEE template + jinja_html
# ----------------------------------------------------------------------------------------------
def jinja_safe(fn):
    """Run an HTML rewrite with every Jinja tag swapped out, so the parser can't escape '<', '>' or '&' inside them."""
    def wrapped(html, *a):
        if "\u27e6J" in html:  # already protected by an outer call
            return fn(html, *a)
        tags = []
        def keep(mo):
            tags.append(mo.group(0)); return "\u27e6J%d\u27e7" % (len(tags) - 1)
        out = fn(JINJA_RE.sub(keep, html), *a)
        return re.sub("\u27e6J(\\d+)\u27e7", lambda mo: tags[int(mo.group(1))], out)
    return wrapped

@jinja_safe
def mce(html):
    """Mirror every style="X" with data-mce-style="X" (the Visual Builder rejects a save without it)."""
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.find_all(True):
        if el.has_attr("style"):
            el["data-mce-style"] = el["style"]
        elif el.has_attr("data-mce-style"):
            del el["data-mce-style"]
    return str(soup)

@jinja_safe
def inline_head_rules(html, rules):
    """Push head-level h1-h6/p rules onto the elements (BEE drops <head> CSS)."""
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.find_all(re.compile(r"^(h[1-6]|p)$")):
        base = dict(rules.get(el.name, {}))
        if el.name == "p":
            base = {k: v for k, v in base.items() if k in ("margin", "margin-top", "margin-bottom", "padding-bottom", "line-height")}
        merged = {**base, **parse_style(el.get("style"))}
        merged.pop("margin-left", None); merged.pop("margin-right", None)
        if merged:
            el["style"] = style_str(merged)
    for a in soup.find_all("a"):
        st = parse_style(a.get("style"))
        if "color" not in st and rules.get("a", {}).get("color"):
            st["color"] = rules["a"]["color"]
            a["style"] = style_str(st)
    return str(soup)

TYPO = ("font-family", "font-size", "font-weight", "font-style", "color", "letter-spacing", "text-transform", "line-height")
BLOCK_TAGS = ("p", "div", "table", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6")

def pct_lh(v):
    """Unitless line-height -> percent (the Visual Builder converts it anyway)."""
    v = str(v or "").strip()
    return f"{float(v) * 100:g}%" if re.fullmatch(r"\d+(\.\d+)?", v) else v

@jinja_safe
def normalize_text(html, rules):
    """Make exported text HTML survive TinyMCE: inline head CSS, hoist a single wrapping span's
    typography onto its block (the editor strips fonts it doesn't know from spans), and turn
    top-level <div>s into <p>s (TinyMCE wraps loose divs in <p>, adding blank lines)."""
    soup = BeautifulSoup(inline_head_rules(html, rules), "html.parser")
    for el in soup.find_all(re.compile(r"^(h[1-6]|p)$")):
        kids = [c for c in el.contents if not (isinstance(c, NavigableString) and not c.strip())]
        if len(kids) == 1 and getattr(kids[0], "name", None) == "span":
            sp = kids[0]
            sst = parse_style(sp.get("style"))
            est = parse_style(el.get("style"))
            moved = {k: v for k, v in sst.items() if k in TYPO}
            if moved:
                est.update(moved)
                el["style"] = style_str(est)
                rest = {k: v for k, v in sst.items() if k not in TYPO}
                if rest:
                    sp["style"] = style_str(rest)
                else:
                    sp.unwrap()
    for el in list(soup.find_all("div", recursive=False)):
        if not el.find(BLOCK_TAGS):
            el.name = "p"
            st = parse_style(el.get("style"))
            if not any(k.startswith("margin") for k in st):
                st.update({"margin-top": "0", "margin-bottom": "0"})
            el["style"] = style_str(st)
    return str(soup)

def single_heading(html):
    """Return the heading tag if the text block is exactly one <h1>-<h6>, else None."""
    soup = BeautifulSoup(html, "html.parser")
    kids = [c for c in soup.contents if not (isinstance(c, NavigableString) and not c.strip())]
    if len(kids) == 1 and getattr(kids[0], "name", "") and re.fullmatch(r"h[1-6]", kids[0].name):
        return kids[0]
    return None

GOOGLE_FONTS = {"Poppins", "Montserrat", "Lato", "Open Sans", "Roboto", "Raleway", "Oswald", "Playfair Display",
                "Merriweather", "Nunito", "Nunito Sans", "Inter", "Work Sans", "DM Sans", "Source Sans Pro", "Ubuntu",
                "Bitter", "Cabin", "Karla", "Rubik", "Mulish", "Josefin Sans", "Libre Baskerville", "Lora",
                "PT Sans", "PT Serif", "Noto Sans", "Noto Serif", "Quicksand", "Barlow", "Manrope", "Archivo",
                "Cormorant Garamond", "EB Garamond", "Space Grotesk", "Outfit", "Jost", "Figtree", "Plus Jakarta Sans"}

def web_fonts(text):
    """BEE webFonts entries (+ <link> hrefs) for Google fonts actually used, so the editor keeps them."""
    names = []
    for stack in re.findall(r"font-family\W{1,4}([^;\"}]+)", text):
        first = stack.split(",")[0].strip().strip("'\\\" ")
        if first in GOOGLE_FONTS and first not in names:
            names.append(first)
    entries = [{"fontFamily": f"'{n}', sans-serif", "name": n,
                "url": f"https://fonts.googleapis.com/css?family={n.replace(' ', '+')}:300,400,500,600,700,800,900"} for n in names]
    return entries

def css_px(v, default=0.0):
    m = re.match(r"(-?\d+(?:\.\d+)?)", str(v or ""))
    return float(m.group(1)) if m else default

def static_href(h):
    """BEE gets static hrefs/srcs; live tokens only in jinja_html."""
    return "#" if (not h or "{{" in h or "{%" in h) else h

def row_type(cols):
    n = len(cols)
    grids = [max(1, round(c["pct"] * 12 / 100)) for c in cols]
    if sum(grids) != 12:
        grids[-1] += 12 - sum(grids)
    if n == 1: return "one-column-empty", [12]
    if n == 2:
        if grids == [4, 8]: return "two-columns-4-8-empty", grids
        if grids == [8, 4]: return "two-columns-8-4-empty", grids
        return "two-columns-6-6-empty", [6, 6]
    if n == 3: return "three-columns-empty", [4, 4, 4]
    if n == 4: return "four-columns-empty", [3, 3, 3, 3]
    return "one-column-empty", [12]

PERC = {1: 100, 2: 94, 3: 96, 4: 94}

def bee_module(b, ctx):
    pad = {f"padding-{k}": v for k, v in b["padding"].items()}
    hide = {"hideContentOnMobile": b["visibility"] == "desktop" and ctx["keep_mobile"]}
    t = b["type"]
    if t == "image":
        w = b["width"]
        dims = ctx["dims"](b.get("src"))
        nat_w, nat_h = (f"{dims[0]}px", f"{dims[1]}px") if dims else (w, "auto")
        col_px = ctx["col_px"]
        perc = PERC.get(ctx["ncols"], 100)
        if css_px(w) and col_px and css_px(w) < col_px * 0.9:
            perc = max(1, round(css_px(w) / col_px * 100))
        return {"type": "mailup-bee-newsletter-modules-image", "locked": False, "uuid": uid(), "align": "left",
                "descriptor": {"computedStyle": {"class": "center fixedwidth", "width": w, **hide},
                               "image": {"alt": b.get("alt", ""), "href": static_href(b.get("href")), "src": ctx["img"](b.get("src")),
                                         "target": "_blank", "width": nat_w, "height": nat_h, "prefix": "",
                                         "percWidth": perc},
                               "style": {**pad, "width": "100%", "text-align": b.get("align", "center")}}}
    if t in ("text", "nav", "html"):
        if t == "nav":
            sep = '<span style="display:inline-block;width:24px" data-mce-style="display:inline-block;width:24px">&nbsp;</span>'
            parts = []
            for l in b["links"]:
                st = {k: v for k, v in l["style"].items() if k in ("color", "font-family", "font-size", "font-weight", "letter-spacing", "text-transform")}
                st["text-decoration"] = "none"
                parts.append(f'<a href="{attr(static_href(l["href"]))}" style="{style_str(st)}">{l["text"]}</a>')
            inner = f'<p style="text-align:center;margin:0">{sep.join(parts)}</p>'
            wst = {"font-family": ctx["font"], "line-height": "1.3", "text-align": "center"}
        else:
            inner = inline_head_rules(b["bee_html"], ctx["rules"]) if t == "html" else normalize_text(b["bee_html"], ctx["rules"])
            wst = {k: v for k, v in b.get("wrapper_style", {}).items() if k in ("font-family", "font-size", "font-style", "font-weight", "letter-spacing", "line-height", "text-align", "color")}
            if "line-height" in wst: wst["line-height"] = pct_lh(wst["line-height"])
            h = single_heading(inner) if t == "text" else None
            if h is not None:
                hst = {**{k: v for k, v in wst.items() if k in TYPO or k == "text-align"}, **parse_style(h.get("style"))}
                return {"type": "mailup-bee-newsletter-modules-heading", "locked": False, "uuid": uid(),
                        "descriptor": {"computedStyle": {"hideContentOnDesktop": False, "hideContentOnMobile": hide["hideContentOnMobile"]},
                                       "heading": {"title": h.name,
                                                   "text": mce(f'<span class="tinyMce-placeholder">{h.decode_contents().strip()}</span>'),
                                                   "style": {"color": hst.get("color", "#000000"), "direction": "ltr",
                                                             "font-family": hst.get("font-family", ctx["font"]),
                                                             "font-size": hst.get("font-size", "24px"), "font-weight": hst.get("font-weight", "400"),
                                                             "letter-spacing": px(hst.get("letter-spacing", "0px")),
                                                             "line-height": pct_lh(hst.get("line-height", "120%")),
                                                             "link-color": ctx["link_color"], "text-align": hst.get("text-align", "left"),
                                                             **({"text-transform": hst["text-transform"]} if hst.get("text-transform") else {}),
                                                             **({"font-style": hst["font-style"]} if hst.get("font-style") else {})}},
                                       "style": {**pad, "text-align": hst.get("text-align", "left"), "width": "100%"}}}
        if t == "html":
            return {"type": "mailup-bee-newsletter-modules-html", "locked": False, "uuid": uid(),
                    "descriptor": {"computedStyle": {"hideContentOnMobile": hide["hideContentOnMobile"]},
                                   "html": {"html": inner}, "style": pad}}
        html = mce(f'<div class="txtTinyMce-wrapper" style="{style_str(wst)}">{inner}</div>')
        return {"type": "mailup-bee-newsletter-modules-text", "locked": False, "uuid": uid(), "align": "left",
                "descriptor": {"computedStyle": hide, "style": pad,
                               "text": {"computedStyle": {"linkColor": ctx["link_color"]}, "html": html,
                                        "style": {"color": wst.get("color", "#000000"), "font-family": wst.get("font-family", ctx["font"]),
                                                  "font-weight": wst.get("font-weight", "400"), "line-height": pct_lh(wst.get("line-height", "150%"))}}}}
    if t == "button":
        ip = b["inner_padding"]
        label = mce(f'<div class="txtTinyMce-wrapper" style=""><p style="word-break:break-word;margin:0"><span class="tinyMce-placeholder" style="">{b["label"]}</span></p></div>')
        fs = css_px(b["font_size"], 16)
        height = round(fs * 1.2 + css_px(ip["top"]) + css_px(ip["bottom"]))
        width = max(60, round(len(b["label"]) * fs * 0.6 + css_px(ip["left"]) + css_px(ip["right"])))
        return {"type": "mailup-bee-newsletter-modules-button", "locked": False, "uuid": uid(), "align": "left",
                "descriptor": {"button": {"label": label,
                                          "style": {"background-color": b["bg"], "border-bottom": b.get("border_bottom") or "0px solid transparent",
                                                    "border-left": "0px solid transparent", "border-radius": b["radius"], "border-right": "0px solid transparent",
                                                    "border-top": "0px solid transparent", "color": b["color"], "direction": "ltr",
                                                    "font-family": b["font_family"], "font-size": b["font_size"], "font-weight": b["font_weight"],
                                                    "letter-spacing": b["letter_spacing"], "line-height": "120%",
                                                    "padding-bottom": ip["bottom"], "padding-left": ip["left"], "padding-right": ip["right"], "padding-top": ip["top"],
                                                    "text-align": "center", "width": "auto"},
                                          "target": "_self"},
                               "computedStyle": {"width": width, "widthType": "px", "height": height},
                               "href": {"name": static_href(b["href"]), "target": "_blank", "type": "web"},
                               "style": {**pad, "text-align": b.get("align", "center")}}}
    if t == "divider":
        return {"type": "mailup-bee-newsletter-modules-divider", "locked": False, "uuid": uid(),
                "descriptor": {"computedStyle": {"align": "center", "hideContentOnMobile": hide["hideContentOnMobile"]},
                               "divider": {"style": {"border-top": b["border"], "width": b["width"]}}, "style": pad}}
    if t == "spacer":
        return {"type": "mailup-bee-newsletter-modules-spacer", "locked": False, "uuid": uid(),
                "descriptor": {"computedStyle": {"hideContentOnMobile": hide["hideContentOnMobile"]}, "spacer": {"style": {"height": b["height"]}}}}
    if t == "social":
        icons = [{"id": uid(), "name": i["name"], "type": "follow", "text": "",
                  "image": {"alt": i["name"], "href": static_href(i["href"]), "prefix": "", "src": ctx["img"](i["src"]),
                            "target": "_self", "title": i["name"]}} for i in b["icons"]]
        iw = int(re.sub(r"\D", "", b["icons"][0]["width"]) or 32)
        return {"type": "mailup-bee-newsletter-modules-social", "locked": False, "uuid": uid(), "align": "left",
                "descriptor": {"computedStyle": {"height": iw, "hideContentOnMobile": False, "iconsDefaultWidth": iw,
                                                 "padding": "0 5px 0 5px", "width": len(icons) * (iw + 10)},
                               "iconsList": {"icons": icons}, "style": {**pad, "text-align": "center"}}}
    raise ValueError(t)

JINJA_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)

def attr(v, ctx=None, what=None):
    """Escape a value for a double-quoted HTML attribute, leaving Jinja tags as they are.

    With ctx and what, also warn when Jinja appears where none is expected (alt, src)."""
    v = str(v or "")
    if what and ctx and JINJA_RE.search(v):
        ctx["warn"](f"Template tags inside an image {what} attribute ({v[:60]!r}); check it renders as intended")
    out, last = [], 0
    for mo in JINJA_RE.finditer(v):
        out.append(htmllib.escape(v[last:mo.start()], quote=True)); out.append(mo.group(0)); last = mo.end()
    out.append(htmllib.escape(v[last:], quote=True))
    return "".join(out)

def html_module(b, ctx):
    """Compact email-safe HTML for one block (jinja_html side)."""
    p = b["padding"]
    pad = f"padding:{p['top']} {p['right']} {p['bottom']} {p['left']}"
    t = b["type"]
    if t == "image":
        img = f'<img src="{attr(ctx["img_live"](b.get("src")), ctx, "src")}" alt="{attr(b.get("alt"), ctx, "alt")}" width="{re.sub(r"[^0-9]","",b["width"]) or 600}" style="display:block;width:100%;max-width:{b["width"]};height:auto;border:0;margin:0 auto">'
        if b.get("href"): img = f'<a href="{attr(b["live_href"])}" target="_blank">{img}</a>'
        return f'<div style="{pad};text-align:{b.get("align","center")}">{img}</div>'
    if t == "nav":
        links = "&nbsp;&nbsp;&nbsp;&nbsp;".join(
            f'<a href="{attr(l["live_href"] or "#")}" style="{style_str({k: v for k, v in l["style"].items() if k in ("color","font-family","font-size","font-weight","letter-spacing","text-transform")})};text-decoration:none">{l["text"]}</a>'
            for l in b["links"])
        return f'<div style="{pad};text-align:center;font-family:{ctx["font"]}">{links}</div>'
    if t in ("text", "html"):
        wst = style_str({k: v for k, v in b.get("wrapper_style", {}).items() if k in ("font-family","font-size","font-style","font-weight","letter-spacing","line-height","text-align","color")})
        body = inline_head_rules(b["live_html"], ctx["rules"]) if t == "html" else normalize_text(b["live_html"], ctx["rules"])
        return f'<div style="{pad};{wst}">{body}</div>'
    if t == "button":
        ip = b["inner_padding"]
        bb = f";border-bottom:{b['border_bottom']}" if b.get("border_bottom") else ""
        st = (f"display:inline-block;background:{b['bg']};color:{b['color']};font-family:{b['font_family']};font-size:{b['font_size']};"
              f"font-weight:{b['font_weight']};letter-spacing:{b['letter_spacing']};line-height:120%;text-decoration:none;"
              f"padding:{ip['top']} {ip['right']} {ip['bottom']} {ip['left']};border-radius:{b['radius']}{bb}")
        return f'<div style="{pad};text-align:{b.get("align","center")}"><a href="{attr(b["live_href"] or "#")}" target="_blank" style="{st}">{b["label"]}</a></div>'
    if t == "divider":
        return f'<div style="{pad}"><div style="border-top:{b["border"]};width:{b["width"]};margin:0 auto;font-size:1px;line-height:1px">&nbsp;</div></div>'
    if t == "spacer":
        return f'<div style="height:{b["height"]};line-height:{b["height"]};font-size:1px">&nbsp;</div>'
    if t == "social":
        icons = "".join(f'<a href="{attr(i["live_href"] or "#")}" target="_blank" style="display:inline-block;margin:0 5px"><img src="{attr(ctx["img_live"](i["src"]), ctx, "src")}" alt="{attr(i["name"], ctx, "alt")}" width="{re.sub(r"[^0-9]","",i["width"]) or 32}" style="display:block;border:0"></a>' for i in b["icons"])
        return f'<div style="{pad};text-align:center">{icons}</div>'
    return ""

def build(args):
    def load(p):
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    model, mapping, meta = load(args.model), load(args.mapping), load(args.meta)
    tr = Translator(mapping, model["tokens"], model.get("esp", "plain"))
    tr.subject = tr.translate_raw(meta["subject"])
    keep_mobile = bool(mapping.get("keep_mobile_variants"))
    image_map = mapping.get("image_map", {})
    placeholder = mapping.get("placeholder_image", "https://placehold.co/600x300/png?text=Image")
    missing_imgs = sum(1 for r in model["rows"] for c in r["columns"] for b in c["blocks"]
                       if b["type"] == "image" and not b.get("src") and (b["visibility"] != "mobile" or keep_mobile))
    def img(src):
        if not src: return placeholder
        v = image_map.get(src, src)
        return v["url"] if isinstance(v, dict) else v
    def dims(src):
        v = image_map.get(src) if src else None
        if isinstance(v, dict) and v.get("width") and v.get("height"):
            return int(v["width"]), int(v["height"])
        return None
    ctx = {"keep_mobile": keep_mobile, "font": model["default_font"], "link_color": model["link_color"],
           "rules": model["head_rules"], "img": img, "img_live": img, "dims": dims, "warn": tr.warnings.append}

    rows_bee, rows_html, block_htmls = [], [], []
    dropped_mobile = 0
    for ri, row in enumerate(model["rows"]):
        rtype, grids = row_type(row["columns"])
        ctx["ncols"] = len(row["columns"])
        bee_cols, html_cols = [], []
        for ci, col in enumerate(row["columns"]):
            ctx["col_px"] = model["width"] * col["pct"] / 100
            mods, hmods = [], []
            # A column background is only safe when every block in the column shares it. Otherwise one
            # block's background (e.g. a coloured banner) would paint the whole column.
            shown = [x for x in col["blocks"] if not (x["visibility"] == "mobile" and not keep_mobile)]
            bgs = {(x.get("background") or "transparent") for x in shown}
            col_bg = col.get("background") or (next(iter(bgs)) if len(bgs) == 1 and "transparent" not in bgs else None)
            for b in col["blocks"]:
                if b["visibility"] == "mobile" and not keep_mobile:
                    dropped_mobile += 1; continue
                b = copy.deepcopy(b)
                own_bg = b.get("background") if b.get("background") not in (None, "", "transparent") else None
                # translate
                if b["type"] in ("text", "html"):
                    live = tr.translate(b["html"])
                    b["live_html"] = live
                    if CONTROL_RE.search(live):
                        b["type"] = "html"  # control flow -> custom HTML module (same Jinja on both sides)
                        tr.note("block with Jinja control flow -> custom HTML module")
                    b["bee_html"] = live
                if b["type"] == "button":
                    b["label"] = tr.translate(b["label"])
                for key in ("href",):
                    if key in b:
                        b["live_href"] = tr.translate(b[key]) if b[key] else ""
                for l in b.get("links", []) + b.get("icons", []):
                    l["live_href"] = tr.translate(l["href"]) if l.get("href") else ""
                if b["type"] == "image" and b.get("href"):
                    b["live_href"] = tr.translate(b["href"])
                if b["type"] == "image":
                    b["alt"] = tr.translate(b.get("alt", ""))
                    if PH_RE.search(b.get("src") or ""):
                        b["src"] = restore(b["src"], model["tokens"])
                        tr.warnings.append(f"An image source holds a template token ({b['src'][:60]}); the Visual Builder gets a placeholder image")
                if own_bg and not col_bg and own_bg.lower() not in (b.get("live_html") or b.get("bee_html") or "").lower():
                    tr.warnings.append(f"A {b['type']} block has background {own_bg} that couldn't be kept (other blocks in its column "
                                       "have none); add it in the Visual Builder if needed")
                mods.append(bee_module(b, ctx))
                hmods.append(html_module(b, ctx))
                block_htmls.append(hmods[-1])
            bee_cols.append({"grid-columns": grids[ci], "modules": mods,
                             "style": {"background-color": col_bg or "transparent", "border-bottom": "0px solid transparent",
                                       "border-left": "0px solid transparent", "border-right": "0px solid transparent",
                                       "border-top": "0px solid transparent", "padding-bottom": "0px", "padding-left": "0px",
                                       "padding-right": "0px", "padding-top": "0px"}, "uuid": uid()})
            html_cols.append(f'<td class="col" width="{col["pct"]:.2f}%" valign="top" style="width:{col["pct"]:.2f}%;vertical-align:top{";background:" + col_bg if col_bg else ""}">{"".join(hmods)}</td>')
        if not any(c["modules"] for c in bee_cols):
            continue
        name = "Row %d" % (len(rows_bee) + 1)
        first_text = next((BeautifulSoup(b.get("html", b.get("label", "")), "html.parser").get_text(" ", strip=True)
                           for c in row["columns"] for b in c["blocks"] if b.get("html") or b.get("label")), "")
        first_text = re.sub(r"\{[{%].*?[}%]\}", "", first_text).strip()
        if first_text: name += " – " + first_text[:40]
        rows_bee.append({"columns": bee_cols,
                         "container": {"style": {"background-color": "transparent", "background-image": "none", "background-position": "top left", "background-repeat": "no-repeat"}},
                         "content": {"computedStyle": {"hideContentOnDesktop": False, "hideContentOnMobile": False, "rowColStackOnMobile": True,
                                                       "rowReverseColStackOnMobile": False, "verticalAlign": "top"},
                                     "style": {"background-color": row["background"], "background-image": "none", "background-position": "top left",
                                               "background-repeat": "no-repeat", "color": "#000000", "width": f"{model['width']}px"}},
                         "empty": False, "locked": False,
                         "metadata": {"_id": uid(), "name": name, "tags": [], "bee_assets_migrated": True, "initiative_id": None,
                                      "is_global_object": False, "parentInitiativeId": None},
                         "synced": False, "type": rtype, "uuid": uid()})
        rows_html.append(f'<tr><td style="background:{row["background"]}"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>{"".join(html_cols)}</tr></table></td></tr>')

    outer = model["head_rules"].get("_outer", {})
    otop, obot = px(outer.get("padding-top", "0px")), px(outer.get("padding-bottom", "0px"))
    def spacer_row(h, label):
        return {"columns": [{"grid-columns": 12, "modules": [{"type": "mailup-bee-newsletter-modules-spacer", "locked": False, "uuid": uid(),
                    "descriptor": {"computedStyle": {"hideContentOnMobile": False}, "spacer": {"style": {"height": h}}}}],
                    "style": {"background-color": "transparent", "border-bottom": "0px solid transparent", "border-left": "0px solid transparent",
                              "border-right": "0px solid transparent", "border-top": "0px solid transparent", "padding-bottom": "0px",
                              "padding-left": "0px", "padding-right": "0px", "padding-top": "0px"}, "uuid": uid()}],
                "container": {"style": {"background-color": "transparent", "background-image": "none", "background-position": "top left", "background-repeat": "no-repeat"}},
                "content": {"computedStyle": {"hideContentOnDesktop": False, "hideContentOnMobile": False, "rowColStackOnMobile": True,
                                              "rowReverseColStackOnMobile": False, "verticalAlign": "top"},
                            "style": {"background-color": "transparent", "background-image": "none", "background-position": "top left",
                                      "background-repeat": "no-repeat", "color": "#000000", "width": f"{model['width']}px"}},
                "empty": False, "locked": False,
                "metadata": {"_id": uid(), "name": label, "tags": [], "bee_assets_migrated": True, "initiative_id": None,
                             "is_global_object": False, "parentInitiativeId": None},
                "synced": False, "type": "one-column-empty", "uuid": uid()}
    spacer_tr = lambda h: f'<tr><td style="height:{h};line-height:{h};font-size:1px">&nbsp;</td></tr>'
    if css_px(otop) > 0:
        rows_bee.insert(0, spacer_row(otop, "Top spacing")); rows_html.insert(0, spacer_tr(otop))
    if css_px(obot) > 0:
        rows_bee.append(spacer_row(obot, "Bottom spacing")); rows_html.append(spacer_tr(obot))
    subject = tr.subject
    bee = {"page": {"body": {"container": {"style": {"background-color": model["body_background"]}},
                             "content": {"computedStyle": {"linkColor": model["link_color"], "messageBackgroundColor": "transparent",
                                                          "messageWidth": f"{model['width']}px"},
                                         "style": {"color": "#000000", "font-family": model["default_font"]}},
                             "type": "mailup-bee-page-properties", "webFonts": []},
                    "description": subject, "rows": rows_bee,
                    "template": {"name": "template-base", "type": "basic", "version": "2.0.0"}, "title": meta.get("node_name", "Email")},
           "comments": {}}
    W = model["width"]
    pre = tr.translate_raw(meta.get("preheader") if meta.get("preheader") is not None else model.get("preheader_in_source", ""))
    pre_html = f'<div style="display:none;max-height:0;overflow:hidden;mso-hide:all">{pre}</div>' if pre else ""
    wf = web_fonts(json.dumps(bee) + "".join(rows_html))
    bee["page"]["body"]["webFonts"] = wf
    links = "".join(f'<link href="{f["url"]}" rel="stylesheet" type="text/css">' for f in wf)
    email_html = ("<!DOCTYPE html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">" + links +
                  f"<title>{subject}</title><style>body{{margin:0;padding:0}}table{{border-collapse:collapse}}img{{border:0;line-height:100%;outline:none;text-decoration:none}}"
                  f"p{{margin:0}}@media only screen and (max-width:{W+20}px){{.wrap{{width:100%!important}}.col{{display:block!important;width:100%!important}}}}</style></head>"
                  f"<body style=\"margin:0;background:{model['body_background']}\">{pre_html}"
                  f"<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" style=\"background:{model['body_background']}\"><tr><td align=\"center\">"
                  f"<table role=\"presentation\" class=\"wrap\" width=\"{W}\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" style=\"width:{W}px;max-width:{W}px\">"
                  + "".join(rows_html) + "</table></td></tr></table></body></html>")
    email_html = re.sub(r">\s+<", "><", email_html)
    email_html = re.sub(r'\sdata-mce-style="[^"]*"', "", email_html)  # BEE-only attribute

    # ---- lint
    unsub = mapping.get("unsubscribe_token", "{{ consent.page }}")
    if unsub not in email_html:
        tr.errors.append(f"No unsubscribe link ({unsub}) in the email — add one before sending")
    if missing_imgs:
        tr.warnings.append(f"{missing_imgs} image(s) had no source; a placeholder image was used — get the real images from the client")
    leftover_cdn = sorted({u for u in re.findall(r'https?://[^"\')\s]+', email_html) if ESP_CDN.search(u)})
    if leftover_cdn:
        tr.warnings.append(f"{len(leftover_cdn)} image(s) or link(s) still on the old ESP's servers — rehost images with "
                           "import_media_file and add them to mapping.image_map; replace ESP tracking/landing links")
    if dropped_mobile:
        tr.note(f"dropped {dropped_mobile} mobile-only duplicate block(s) (desktop version kept for all screens)")
    if "#TODO" in email_html or 'href="#"' in email_html or 'href=""' in email_html:
        tr.warnings.append("Some links are empty ('#') because the source had none — add URLs before sending")

    # leftover source syntax, then a Jinja parse of every block and of the whole email
    tags_only = " ".join(JINJA_RE.findall(email_html + " " + subject + " " + (pre or "")))
    for i, (bad, msg) in enumerate(LEFTOVER):
        scope = tags_only if i >= 5 else email_html + " " + subject + " " + (pre or "")
        for hit in list(re.finditer(bad, scope))[:5]:
            if any(hit.group(0) in src for src in tr.untranslated):
                continue  # already reported as "No translation"
            tr.errors.append(f"{msg}: {scope[max(0, hit.start() - 20):hit.end() + 40]!r}")
    if model.get("esp") == "activecampaign":
        for hit in re.findall(r"%[A-Z][A-Z0-9_-]{2,40}%", email_html)[:5]:
            tr.errors.append(f"Untranslated ActiveCampaign tag: {hit}")
    try:
        import jinja2
        env = jinja2.Environment()
        for label, piece in [("subject", subject), ("preheader", pre or "")] + [("block", m_) for m_ in block_htmls]:
            try:
                env.parse(piece)
            except jinja2.TemplateSyntaxError as e:
                txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", piece)).strip()[:100]
                tr.errors.append(f"Jinja syntax error in a {label} ({e.message}): {txt!r} — "
                                 "a condition or loop may be split across blocks; see the SKILL.md build step")
    except ImportError:
        tr.errors.append("jinja2 isn't installed in the venv; install it to lint the template")

    # ---- scenario payload
    data = {"beefree_template": json.dumps(bee, separators=(",", ":"), ensure_ascii=False), "jinja_html": email_html,
            "subject": subject, "preheader": pre or None,
            "sender_name": meta["sender_name"], "sender_email": meta["sender_email"], "reply_to": None,
            "file_ids": [], "translations": {}}
    if meta.get("provider"): data["provider"] = meta["provider"]
    node = {"id": 1, "type": "send-email-action", "name": meta["node_name"], "x": 300, "y": 0,
            "bee_free_html_output": "compact", "cached_email_hash": secrets.token_hex(32), "communication_type": "",
            "concurrency_limit": None, "consent_category": meta["consent_category"], "consent_category_tracking": None,
            "content_sources": [], "custom_event_properties": [], "custom_headers": None, "email_on_acid_test_id": None,
            "frequency_policy": "unlimited-policy", "general_consent": False, "precedence_bulk": False,
            "recipient_email": None, "recipient_name": None, "template_id": None, "throughput_policy_id": None,
            "transfer_identity": True, "transfer_user_identity": "first_click", "unsubscribe_list": None,
            "url_params": None, "uses_2tnn": False, "design": {"type": "beefree", "data": data}}
    trig = meta.get("trigger") or {"type": "now"}
    if trig["type"] == "event":
        tnode = {"id": 0, "type": "on-event-trigger", "x": 0, "y": 0, "delay_seconds": trig.get("delay_seconds", 30),
                 "event": {"type": trig["event"], "filter": trig.get("filter", [])}}
    else:
        tnode = {"id": 0, "type": "now-trigger", "x": 0, "y": 0}
        if any(re.search(r"\bevent\s*[.\[|]", t) for t in JINJA_RE.findall(email_html)):
            tr.errors.append("Email uses trigger-event data (event.*) but meta.trigger is 'now' — set an event trigger")
    payload = {"name": meta["scenario_name"], "nodes": [tnode, node],
               "connections": [{"source": {"node_id": 0, "connector_index": 0}, "destination": {"node_id": 1, "connector_index": 0}}],
               "last_node_id": 1}

    # ---- BEE structural validation (the rules in references/bee-schema.md)
    ids = []
    for row in bee["page"]["rows"]:
        ids += [row["uuid"], row["metadata"]["_id"]]
        for col in row["columns"]:
            ids.append(col["uuid"])
            for mod in col["modules"]:
                ids.append(mod["uuid"]); d = mod["descriptor"]; t = mod["type"]
                if "mobileStyle" in d: tr.errors.append("mobileStyle in module")
                if any(t.endswith(x) for x in ("heading", "spacer", "divider", "html")) and "align" in mod: tr.errors.append(f"align not allowed on {t}")
                if t.endswith("-text"):
                    h = d["text"]["html"]
                    if "txtTinyMce-wrapper" not in h: tr.errors.append("text module missing txtTinyMce-wrapper")
                    mc = len(re.findall(r"data-mce-style=", h))
                    if len(re.findall(r"\bstyle=", h)) - mc != mc: tr.errors.append("style=/data-mce-style= mismatch in text module")
                if t.endswith("-button") and not isinstance(d["href"]["name"], str): tr.errors.append("button href must be a string")
    if len(ids) != len(set(ids)): tr.errors.append("duplicate uuids")

    os.makedirs(args.out_dir, exist_ok=True)
    with open(f"{args.out_dir}/bee.json", "w", encoding="utf-8") as fh:
        json.dump(bee, fh, ensure_ascii=False)
    with open(f"{args.out_dir}/email.html", "w", encoding="utf-8") as fh:
        fh.write(email_html)
    s = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    open(f"{args.out_dir}/payload.json", "w", encoding="utf-8").write(s)
    result = {"ok": not tr.errors, "rows": len(rows_bee), "payload_chars": len(s),
              "beefree_template_chars": len(data["beefree_template"]), "jinja_html_chars": len(email_html),
              "changes": tr.log, "errors": sorted(set(tr.errors)), "warnings": sorted(set(tr.warnings))}
    print(json.dumps(result, indent=1, ensure_ascii=False))
    sys.exit(0 if result["ok"] else 1)

# ----------------------------------------------------------------------------------------------
# RENDER-CHECK
# ----------------------------------------------------------------------------------------------
def render_check(args):
    import jinja2, jinja2.sandbox
    with open(args.context, encoding="utf-8") as fh:
        ctxd = json.load(fh)
    undefined = []
    class Rec(jinja2.ChainableUndefined):
        def __str__(self):
            undefined.append(self._undefined_name); return ""
    class Catalog:
        def __init__(self, items): self.items = items
        def item_by_id(self, i): return self.items.get(str(i))
    class Pool:
        def __init__(self, n): self.n = n
        def assign_available(self, cached=True): return f"TEST-{self.n.upper()[:6]}-CODE"
    class Pools(dict):
        def __missing__(self, k): return Pool(k)
    cats = {k: Catalog(v) for k, v in ctxd.get("catalogs", {}).items()}
    recs_items = list(next(iter(ctxd.get("catalogs", {}).values()), {}).values())
    # The template comes from a client's export, so render it sandboxed.
    env = jinja2.sandbox.SandboxedEnvironment(undefined=Rec)
    env.filters["from_timestamp"] = lambda ts, fmt=None: (datetime.datetime.fromtimestamp(float(ts), datetime.timezone.utc)
                                                          .strftime(fmt) if fmt else datetime.datetime.fromtimestamp(float(ts), datetime.timezone.utc))
    html = open(args.html, encoding="utf-8").read()
    try:
        out = env.from_string(html).render(customer=ctxd.get("customer", {}), event=ctxd.get("event", {}), catalogs=cats,
                                            aggregates=ctxd.get("aggregates", {}),
                                            vouchers=Pools(), project_variables=ctxd.get("project_variables", {}),
                                            consent={"page": "https://consent.example/page"},
                                            email={"view": "https://view.example", "unsubscribe": "https://unsub.example"},
                                            recommendations=lambda *a, **k: recs_items[: (a[1] if len(a) > 1 else 4)],
                                            sent_timestamp=time.time(),
                                            brand_name=ctxd.get("project_variables", {}).get("company_name", ""))
    except jinja2.TemplateError as e:  # includes SecurityError
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"})); sys.exit(1)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(out)
    text = BeautifulSoup(out, "html.parser").get_text(" ", strip=True)
    print(json.dumps({"ok": True, "undefined_references": sorted(set(undefined)),
                      "visible_text_preview": text[:600],
                      "leftover_tags": re.findall(r"\{[{%].*?[}%]\}", out)[:10]}, indent=1, ensure_ascii=False))


# ----------------------------------------------------------------------------------------------
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # names and copy can hold any character; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup"); s.add_argument("--venv", required=True)
    a = sub.add_parser("analyze"); a.add_argument("export"); a.add_argument("--out-dir", required=True)
    a.add_argument("--esp", choices=ESPS + ("jinja-like", "plain"), help="override the detected ESP")
    b = sub.add_parser("build")
    for f in ("--model", "--mapping", "--meta", "--out-dir"): b.add_argument(f, required=True)
    r = sub.add_parser("render-check"); r.add_argument("--html", required=True); r.add_argument("--context", required=True); r.add_argument("--out")
    for p in (a, b, r): p.add_argument("--venv")
    args = ap.parse_args()
    if args.cmd == "analyze": analyze(args.export, args.out_dir, args.esp)
    elif args.cmd == "build": build(args)
    else: render_check(args)
