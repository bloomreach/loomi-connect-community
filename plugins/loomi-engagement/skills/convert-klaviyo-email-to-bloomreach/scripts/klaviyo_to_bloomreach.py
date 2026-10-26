#!/usr/bin/env python3
"""Klaviyo HTML export -> Bloomreach Engagement (BEE template + jinja_html + scenario payload).

Subcommands
  setup    --venv DIR
      Create a virtual environment at DIR (standard library only, no network) and print the
      pip command that installs beautifulsoup4 and jinja2 into it.
  analyze  <export.html> --out-dir DIR
      Parse the export into DIR/model.json and print a migration report (JSON):
      tokens found, images to rehost, flow/event usage, dead links, placeholder copy,
      desktop/mobile differences, hardcoded discount codes.
  build    --model DIR/model.json --mapping mapping.json --meta meta.json --out-dir DIR
      Translate Klaviyo template tags to Bloomreach Jinja using mapping.json, then write
      DIR/bee.json, DIR/email.html, DIR/payload.json (create_scenario payload) and print a
      change log + lint result. Exit code 1 if lint finds blocking errors.
  render-check --html DIR/email.html --context ctx.json
      Render jinja_html locally with Jinja2 against real project data (customer properties,
      catalog items, trigger event) to catch template errors before pushing.

Every subcommand except setup takes --venv DIR and re-runs itself with that environment's
Python, so beautifulsoup4 and jinja2 (render-check) never need installing into the system Python.
"""
import argparse, copy, json, os, re, secrets, sys, uuid

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
        os.execv(py, [py, os.path.realpath(__file__)] + argv[1:])

bootstrap_venv(sys.argv)

try:
    from bs4 import BeautifulSoup, NavigableString, Comment
except ImportError:
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
    return out

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
# ANALYZE: Klaviyo export -> block model
# ----------------------------------------------------------------------------------------------
def head_rules(soup):
    """Collect simple element rules (h1-h4, p, a) from <style> blocks, ignoring media queries."""
    css = " ".join(s.get_text() for s in soup.find_all("style"))
    css = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    rules = {}
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        for s in sel.split(","):
            s = s.strip()
            if re.fullmatch(r"h[1-6]|p", s):
                rules.setdefault(s, {}).update(parse_style(body))
            if s == ".root-container-spacing":
                rules.setdefault("_outer", {}).update(parse_style(body.replace("!important", "")))
            if s in ("a:link", "a:not([name])"):
                rules.setdefault("a", {}).update(parse_style(body))
    return rules

def classes(tag):
    return tag.get("class") or []

def visibility(wrapper):
    c = classes(wrapper)
    if "desktop-only" in c: return "desktop"
    if "mobile-only" in c: return "mobile"
    return "all"

def component_cell(wrapper):
    """The <td> inside a component-wrapper that carries block padding/background."""
    tbl = wrapper.find("table")
    return tbl.find("td") if tbl else None

def parse_block(wrapper, warnings, col_px):
    cell = component_cell(wrapper)
    cst = parse_style(cell.get("style")) if cell else {}
    pad = padding_of(cst)
    bg = cst.get("background-color") or cst.get("background")
    base = {"visibility": visibility(wrapper), "padding": pad, "background": bg}

    # --- header link bar (logo + nav links)
    if "hlb-wrapper" in classes(wrapper):
        blocks = []
        logo_td = wrapper.find("td", class_=lambda c: c and "hlb-logo" in c and "table-mobile-only" not in c)
        if logo_td and logo_td.find("img"):
            img = logo_td.find("img"); a = img.find_parent("a")
            blocks.append({**base, "type": "image", "src": img.get("src", ""), "alt": img.get("alt", "Logo"),
                           "href": a.get("href", "") if a else "", "width": px(img.get("width") or "200"),
                           "align": "center", "role": "logo"})
        links = []
        for sub in wrapper.find_all("td", class_=lambda c: c and "hlb-subblk" in c):
            el = sub.find("a") or sub.find("p")
            if not el: continue
            txt = el.get_text(" ", strip=True)
            if not txt: continue
            href = el.get("href", "") if el.name == "a" else ""
            if not href:
                warnings.append(f"Nav link '{txt}' has no URL in the Klaviyo source")
            links.append({"text": txt, "href": href, "style": parse_style(el.get("style"))})
        if links:
            blocks.append({**base, "type": "nav", "links": links})
        return blocks

    # --- text
    tdt = wrapper.find("td", class_=lambda c: c and "kl-text" in c)
    if tdt:
        div = tdt.find("div")
        inner_pad = padding_of(parse_style(tdt.get("style")))
        p = {k: add_px(pad[k], inner_pad[k]) for k in pad}
        html = div.decode_contents() if div else tdt.decode_contents()
        tbg = parse_style(tdt.get("style")).get("background")
        return [{**base, "padding": p, "background": bg or tbg, "type": "text",
                 "wrapper_style": parse_style(div.get("style")) if div else {}, "html": html.strip()}]

    # --- image
    tdi = wrapper.find("td", class_=lambda c: c and "kl-image" in c)
    if tdi:
        img = tdi.find("img"); a = img.find_parent("a") if img else None
        holder = tdi.find("td", class_=lambda c: c and "kl-img" in c)
        hpad = padding_of(parse_style(holder.get("style"))) if holder else {}
        p = {k: add_px(pad[k], hpad.get(k, "0px")) for k in pad}
        src = img.get("src", "") if img else ""
        if not src:
            warnings.append("Image block with no image source in the Klaviyo export (unfinished template)")
        return [{**base, "padding": p, "type": "image", "src": src, "alt": (img.get("alt") or "").strip() if img else "",
                 "href": a.get("href", "") if a else "", "width": px(img.get("width") if img else col_px),
                 "align": tdi.get("align", "center")}]

    # --- button
    tdb = wrapper.find("td", class_=lambda c: c and "kl-button" in c)
    if tdb:
        btn_td = tdb.find("td", attrs={"bgcolor": True}) or tdb.find("td")
        bst = parse_style(btn_td.get("style")) if btn_td else {}
        el = btn_td.find("a") or btn_td.find("p") if btn_td else None
        est = parse_style(el.get("style")) if el else {}
        label = el.get_text(" ", strip=True) if el else "Button"
        href = el.get("href", "") if el is not None and el.name == "a" else ""
        if not href:
            warnings.append(f"Button '{label}' has no link in the Klaviyo source")
        return [{**base, "type": "button", "label": label, "href": href, "align": tdb.get("align", "center"),
                 "bg": btn_td.get("bgcolor") or bst.get("background") or "#000000",
                 "color": est.get("color") or bst.get("color") or "#ffffff",
                 "font_family": est.get("font-family") or bst.get("font-family") or "Arial, sans-serif",
                 "font_size": est.get("font-size") or bst.get("font-size") or "16px",
                 "font_weight": est.get("font-weight") or bst.get("font-weight") or "400",
                 "radius": est.get("border-radius") or bst.get("border-radius") or "0px",
                 "inner_padding": padding_of(est) if "padding" in est else {"top": "11px", "right": "20px", "bottom": "11px", "left": "20px"},
                 "letter_spacing": est.get("letter-spacing", "0px"),
                 "border_bottom": bst.get("border-bottom")}]

    # --- divider
    pdiv = wrapper.find("p", style=lambda s: s and "border-top" in s)
    if pdiv:
        dst = parse_style(pdiv.get("style"))
        return [{**base, "type": "divider", "border": dst.get("border-top", "1px solid #BBBBBB").replace("solid ", "solid "),
                 "width": dst.get("width", "100%")}]

    # --- social (several linked icons)
    def small(img):
        w = re.sub(r"\D", "", str(img.get("width") or parse_style(img.get("style")).get("width", "")))
        return w and int(w) <= 64
    icons = [i for i in wrapper.find_all("img") if small(i)]
    if len(icons) >= 2 and not wrapper.find("td", class_=lambda c: c and ("kl-text" in c or "kl-button" in c)):
        out = []
        for img in icons:
            a = img.find_parent("a")
            href = a.get("href", "") if a else ""
            name = (img.get("alt") or "Link").strip().title()
            if not href:
                warnings.append(f"Social icon '{name}' has no link in the Klaviyo source")
            out.append({"name": name, "href": href, "src": img.get("src", ""), "width": px(img.get("width") or "32")})
        return [{**base, "type": "social", "icons": out}]

    # --- spacer
    sp = wrapper.find("div", style=lambda s: s and "height:" in s)
    if sp and not wrapper.get_text(strip=True).replace(" ", ""):
        return [{**base, "type": "spacer", "height": parse_style(sp.get("style")).get("height", "20px")}]

    # --- single image without kl-image wrapper
    img = wrapper.find("img")
    if img:
        a = img.find_parent("a")
        return [{**base, "type": "image", "src": img.get("src", ""), "alt": img.get("alt", ""),
                 "href": a.get("href", "") if a else "", "width": px(img.get("width") or col_px), "align": "center"}]

    html = wrapper.decode_contents().strip()
    if wrapper.get_text(strip=True):
        warnings.append("Unrecognised Klaviyo block converted to a custom HTML module: " + wrapper.get_text(" ", strip=True)[:60])
        return [{**base, "type": "html", "html": html}]
    return []

def section_background(row):
    for anc in row.parents:
        if anc.name == "div":
            st = parse_style(anc.get("style"))
            bg = st.get("background-color") or st.get("background")
            if bg:
                return bg
        if anc.name == "body":
            break
    return "transparent"

def analyze(path, out_dir):
    raw = open(path, encoding="utf-8").read()
    soup = BeautifulSoup(raw, "html.parser")
    warnings = []
    rules = head_rules(soup)
    body = soup.body
    bst = parse_style(body.get("style") if body else "")
    root = soup.find("div", id="bodyTable")
    body_bg = bst.get("background-color") or (parse_style(root.get("style")).get("background-color") if root else None) or "#ffffff"
    # content width = most common max-width on inline style attributes (not media queries)
    widths = [int(w) for w in re.findall(r'style="[^"]*?max-width:\s*(\d+)px', raw)]
    width = max(set(widths), key=widths.count) if widths else 600
    link_color = rules.get("a", {}).get("color", "#0000EE")

    rows = []
    for ri, row in enumerate(soup.select("div.kl-row")):
        cols = []
        for col in row.find_all("div", class_="kl-column", recursive=False):
            m = re.search(r"width:\s*([\d.]+)%", col.get("style", ""))
            pct = float(m.group(1)) if m else 100.0
            col_px = f"{int(width * pct / 100)}px"
            blocks = []
            for w in col.find_all("div", class_="component-wrapper", recursive=False):
                blocks += parse_block(w, warnings, col_px)
            cols.append({"pct": pct, "blocks": blocks})
        rows.append({"background": section_background(row), "columns": cols})

    # klaviyo branding / pixels are outside kl-rows and are dropped by construction
    fonts = sorted(set(re.findall(r"font-family:\s*['\"]?([A-Za-z][\w ]+?)['\"]?[,;]", raw)))
    model = {"source": path, "width": width, "body_background": body_bg, "link_color": link_color,
             "head_rules": rules, "rows": rows,
             "default_font": rules.get("h1", {}).get("font-family", "Arial, sans-serif")}
    import os
    os.makedirs(out_dir, exist_ok=True)
    json.dump(model, open(f"{out_dir}/model.json", "w"), indent=1)

    # ---------------- report
    text_all = raw
    tags = sorted(set(m.strip() for m in re.findall(r"\{[{%].*?[}%]\}", text_all, re.S)))
    imgs = sorted(set(re.findall(r'src="(https?://[^"]+)"', raw)))
    imgs = [u for u in imgs if "/branding/" not in u]  # 'Powered by Klaviyo' badge is dropped
    klaviyo_imgs = [u for u in imgs if re.search(r"klaviyo|d3k81ch9hvuctc\.cloudfront\.net", u)]
    vis_diff = []
    for ri, r in enumerate(rows):
        for ci, c in enumerate(r["columns"]):
            d = [BeautifulSoup(b.get("html", b.get("label", "")), "html.parser").get_text(" ", strip=True)
                 for b in c["blocks"] if b["visibility"] == "desktop"]
            m_ = [BeautifulSoup(b.get("html", b.get("label", "")), "html.parser").get_text(" ", strip=True)
                  for b in c["blocks"] if b["visibility"] == "mobile"]
            for t in d:
                if t and t not in m_:
                    vis_diff.append(f"row {ri} col {ci}: desktop-only content not in mobile version: '{t[:70]}'")
            for t in m_:
                if t and t not in d:
                    vis_diff.append(f"row {ri} col {ci}: mobile-only content not in desktop version: '{t[:70]}'")
    plain = soup.get_text(" ", strip=True)
    codes = sorted(set(re.findall(r"\b(?:code|coupon|promo)\b[^A-Za-z0-9]{0,20}([A-Z0-9][A-Z0-9_-]{3,})", plain, re.I)))
    report = {
        "rows": len(rows),
        "blocks": sum(len(c["blocks"]) for r in rows for c in r["columns"]),
        "width_px": width,
        "klaviyo_tags": tags,
        "uses_event_data": bool(re.search(r"\{[{%][^}%]*\bevent\b", raw)),
        "uses_catalog_lookup": "{% catalog" in raw,
        "uses_coupon": "coupon_code" in raw,
        "images_total": len(imgs),
        "images_on_klaviyo_cdn": klaviyo_imgs,
        "fonts_used": fonts,
        "klaviyo_font_import": bool(re.search(r"static-forms\.klaviyo\.com", raw)),
        "hardcoded_codes": codes,
        "placeholder_copy": bool(re.search(r"lorem ipsum|\bHEADLINE\b|ADD YOUR CTA|Product Title", plain, re.I)),
        "desktop_mobile_differences": vis_diff,
        "warnings": sorted(set(warnings)),
    }
    print(json.dumps(report, indent=1))

# ----------------------------------------------------------------------------------------------
# TRANSLATE: Klaviyo template language -> Bloomreach Jinja
# ----------------------------------------------------------------------------------------------
class Translator:
    def __init__(self, mapping):
        self.m = mapping
        self.log = {}
        self.errors = []
        self.warnings = []

    def note(self, rule, n=1):
        if n:
            self.log[rule] = self.log.get(rule, 0) + n

    def prop(self, kprop):
        """Klaviyo profile property -> Bloomreach customer expression."""
        std = self.m.get("customer_properties", {})
        custom = self.m.get("custom_properties", {})
        if kprop in std:
            p = std[kprop]
        elif kprop in custom:
            p = custom[kprop]
        else:
            p = kprop
            self.warnings.append(f"Profile property '{kprop}' has no confirmed Bloomreach mapping; used '{p}' as-is")
        if p is None:
            self.warnings.append(f"Profile property '{kprop}' does not exist in the project; replaced with empty value")
            return "''"
        return f"customer.{p}" if re.fullmatch(r"[A-Za-z_]\w*", p) else f"customer['{p}']"

    def django_filters(self, s):
        s2 = re.sub(r"\|\s*default:\s*(['\"])(.*?)\1", r" | default(\1\2\1)", s)
        s2 = re.sub(r"\|\s*default:\s*([\w.]+)", r" | default(\1)", s2)
        s2 = re.sub(r"\|\s*floatformat:\s*0\b", r" | float | round(0) | int", s2)
        s2 = re.sub(r"\|\s*floatformat:\s*(\d+)", r" | float | round(\1)", s2)
        s2 = re.sub(r"\|\s*floatformat\b", r" | float | round(1)", s2)
        s2 = re.sub(r"\|\s*lookup:\s*(['\"])(.*?)\1", r"['\2']", s2)
        s2 = re.sub(r"\|\s*truncatechars:\s*(\d+)", r" | truncate(\1)", s2)
        s2 = re.sub(r"\|\s*(upper|lower|title|capitalize|length|trim)\b", r" | \1", s2)
        if s2 != s:
            self.note("Django filter syntax (|default:'x', |lookup:'k', |floatformat) -> Jinja")
        return s2

    def translate(self, html, context="text"):
        m = self.m
        h = html

        # profile properties
        def rp_lookup(mo):
            return self.prop(mo.group(2))
        h, n = re.subn(r"person\s*\|\s*lookup:\s*(['\"])(.*?)\1", rp_lookup, h); self.note("person|lookup:'X' -> customer property", n)
        h, n = re.subn(r"\bperson\.(\w+)", lambda mo: self.prop(mo.group(1)), h); self.note("person.<prop> -> customer property", n)
        # Klaviyo shorthand merge tags without person.
        for short in ("first_name", "last_name", "email", "phone_number"):
            h, n = re.subn(r"\{\{\s*" + short + r"\b", "{{ " + self.prop(short), h)
            self.note(f"{{{{ {short} }}}} shorthand -> customer property", n)

        # organization tags
        org = m.get("organization", {})
        for key in ("name", "full_address", "url"):
            pat = r"\{\{\s*organization\." + key + r"\s*\}\}"
            if re.search(pat, h):
                val = org.get(key)
                if val:
                    h = re.sub(pat, lambda _: val, h); self.note(f"organization.{key} -> {val}")
                else:
                    h = re.sub(pat, f"<!-- TODO: {key.replace('_', ' ')} missing in project -->", h)
                    self.errors.append(f"organization.{key} has no Bloomreach value (set a project variable or literal in mapping.organization.{key})")

        # unsubscribe / preferences / web view
        unsub = m.get("unsubscribe_token", "{{ consent.page }}")
        link_style = 'style="color:inherit;text-decoration:underline" data-mce-style="color:inherit;text-decoration:underline"'
        h, n = re.subn(r"\{%\s*unsubscribe\s+(['\"])(.*?)\1\s*%\}", lambda mo: f'<a href="{unsub}" {link_style}>{mo.group(2)}</a>', h); self.note("{% unsubscribe 'text' %} -> unsubscribe link", n)
        h, n = re.subn(r"\{%\s*unsubscribe\s*%\}", f'<a href="{unsub}" {link_style}>Unsubscribe</a>', h); self.note("{% unsubscribe %} -> unsubscribe link", n)
        h, n = re.subn(r"\{%\s*unsubscribe_url\s*%\}", unsub, h); self.note("{% unsubscribe_url %} -> unsubscribe URL", n)
        h, n = re.subn(r"\{%\s*manage_preferences\s+(['\"])(.*?)\1\s*%\}", lambda mo: f'<a href="{unsub}" {link_style}>{mo.group(2)}</a>', h); self.note("{% manage_preferences 'text' %} -> preferences link", n)
        h, n = re.subn(r"\{%\s*manage_preferences\s*%\}", f'<a href="{unsub}" {link_style}>Manage preferences</a>', h); self.note("{% manage_preferences %} -> preferences link", n)
        h, n = re.subn(r"\{%\s*web_view\s+(['\"])(.*?)\1\s*%\}", lambda mo: f'<a href="{{{{ email.view }}}}" {link_style}>{mo.group(2)}</a>', h); self.note("{% web_view 'text' %} -> email.view link", n)
        h, n = re.subn(r"\{%\s*web_view\s*%\}", f'<a href="{{{{ email.view }}}}" {link_style}>View in browser</a>', h); self.note("{% web_view %} -> email.view link", n)
        h, n = re.subn(r"\{%\s*web_view_url\s*%\}", "{{ email.view }}", h); self.note("{% web_view_url %} -> email.view", n)

        # coupons -> vouchers
        def coupon(mo):
            kname = mo.group(2)
            pool = m.get("voucher_pools", {}).get(kname)
            if not pool:
                self.errors.append(f"Klaviyo coupon '{kname}' has no Bloomreach voucher pool in mapping.voucher_pools")
                return f"<!-- TODO voucher pool for Klaviyo coupon '{kname}' -->"
            return "{{ vouchers['%s'].assign_available() }}" % pool
        h, n = re.subn(r"\{%\s*coupon_code\s+(['\"])(.*?)\1\s*%\}", coupon, h); self.note("{% coupon_code 'X' %} -> vouchers['pool'].assign_available()", n)

        # event-driven catalog loops
        cat = m.get("catalog")
        lists = m.get("event_lists", {})
        idf = m.get("event_list_id_field")
        cur = m.get("currency_symbol", "$")
        loop = re.compile(r"\{%\s*for\s+(\w+)\s+in\s+event\.([\w.]+)\s*%\}(.*?)\{%\s*endfor\s*%\}", re.S)
        def rw_loop(mo):
            var, klist, body = mo.group(1), mo.group(2), mo.group(3)
            if "{% catalog" not in body:
                if klist in lists:
                    self.warnings.append(f"Loop over event.{klist} (no catalog lookup) mapped to event.{lists[klist]}; check the item fields inside it")
                    return "{%% for %s in event.%s %%}%s{%% endfor %%}" % (var, lists[klist], body)
                self.errors.append(f"Loop over event.{klist} has no mapping in mapping.event_lists")
                return mo.group(0)
            if not cat:
                self.errors.append("Catalog loop found but mapping.catalog is not set"); return mo.group(0)
            if klist not in lists:
                self.errors.append(f"Catalog loop over event.{klist} has no mapping in mapping.event_lists"); return mo.group(0)
            body = re.sub(r"\{%\s*catalog\s+\w+[^%]*%\}", "", body)
            body = re.sub(r"\{%\s*endcatalog\s*%\}", "", body)
            fmap = m.get("catalog_fields", {})
            def field(kpath):
                return fmap.get(kpath, kpath)
            body = re.sub(r"\{%\s*currency_format\s+catalog_item\.metadata\s*\|\s*lookup:\s*\"\$price\"\s*%\}",
                          cur + "{{ '%.2f' | format(item." + field("price") + " | float) }}", body)
            body = re.sub(r"\{%\s*currency_format\s+([^%]+?)\s*%\}", lambda mo2: cur + "{{ '%.2f' | format(" + mo2.group(1) + " | float) }}", body)
            for kp in ("featured_image.thumbnail.src", "featured_image.full.src"):
                body = body.replace("catalog_item." + kp, "item." + field("image"))
            body = re.sub(r"catalog_item\.metadata\s*\|\s*lookup:\s*\"\$(\w+)\"", lambda mo2: "item." + field(mo2.group(1)), body)
            body = re.sub(r"catalog_item\.(\w+)", lambda mo2: "item." + field(mo2.group(1)), body)
            pid = f"product.{idf}" if idf else "product"
            agg = m.get("event_list_aggregates", {}).get(klist)
            if agg:
                source = "aggregates['%s']" % agg
                self.note("cart loop reads the 'latest cart' aggregate (current cart, works in preview and after waits)")
            else:
                source = "event.%s" % lists[klist]
                self.warnings.append(
                    f"Cart loop reads the triggering event (event.{lists[klist]}), so each run shows only that event's snapshot "
                    "and previews may show a single item. Prefer an aggregate of the last cart event's list "
                    "(mapping.event_list_aggregates) — see references/klaviyo-syntax.md.")
            return ("{%% for product in %s %%}{%% set item = catalogs.%s.item_by_id(%s) %%}{%% if item %%}%s{%% endif %%}{%% endfor %%}"
                    % (source, cat, pid, body))
        h, n = loop.subn(rw_loop, h); self.note("event loop + {% catalog %} -> catalogs.<catalog>.item_by_id()", n)
        h, n = re.subn(r"\{%\s*currency_format\s+([^%]+?)\s*%\}", lambda mo: cur + "{{ '%.2f' | format(" + mo.group(1) + " | float) }}", h); self.note("{% currency_format x %} -> formatted number", n)

        # remaining event.* references
        for ev in sorted(set(re.findall(r"\bevent(?:\.[\w.]+|\s*\|\s*lookup:\s*['\"][^'\"]+['\"])", h))):
            if not ev.startswith("event.product_list") and not any(ev == f"event.{v}" for v in lists.values()):
                self.warnings.append(f"Trigger-event reference '{ev}' kept; confirm the property exists on the Bloomreach trigger event")

        # Django filter syntax inside Jinja delimiters only
        h = re.sub(r"\{\{.*?\}\}|\{%.*?%\}", lambda mo: self.django_filters(mo.group(0)), h, flags=re.S)

        # lint for leftovers
        for bad, msg in ((r"\{%\s*(catalog|endcatalog|unsubscribe|web_view|coupon_code|currency_format|manage_preferences|include|firstof|with|endwith)\b", "Untranslated Klaviyo tag"),
                         (r"\bperson\b[.|]", "Untranslated Klaviyo person reference"),
                         (r"\borganization\.", "Untranslated organization tag"),
                         (r"\|\s*\w+:", "Django-style filter argument"),
                         (r"\{\{\s*voucher\(", "Invalid voucher syntax (use vouchers['pool'].assign_available())")):
            scope = h if msg.startswith(("Untranslated Klaviyo tag", "Invalid voucher")) else " ".join(re.findall(r"\{\{.*?\}\}|\{%.*?%\}", h, re.S))
            for hit in re.finditer(bad, scope):
                self.errors.append(f"{msg}: {scope[max(0, hit.start()-20):hit.end()+40]!r}")
        return h

# ----------------------------------------------------------------------------------------------
# BUILD: model -> BEE template + jinja_html
# ----------------------------------------------------------------------------------------------
def mce(html):
    """Mirror every style="X" with data-mce-style="X" (BEE multiparser requirement)."""
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.find_all(True):
        if el.has_attr("style"):
            el["data-mce-style"] = el["style"]
        elif el.has_attr("data-mce-style"):
            del el["data-mce-style"]
    return str(soup)

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

def normalize_text(html, rules):
    """Make Klaviyo text HTML survive TinyMCE: inline head CSS, hoist a single wrapping span's
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
            st = parse_style(el.get("style")); st.setdefault("margin", "0")
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
                parts.append(f'<a href="{static_href(l["href"])}" style="{style_str(st)}">{l["text"]}</a>')
            inner = f'<p style="text-align:center;margin:0">{sep.join(parts)}</p>'
            wst = {"font-family": ctx["font"], "line-height": "1.3", "text-align": "center"}
        else:
            inner = b["bee_html"] if t == "html" else normalize_text(b["bee_html"], ctx["rules"])
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

def html_module(b, ctx):
    """Compact email-safe HTML for one block (jinja_html side)."""
    p = b["padding"]
    pad = f"padding:{p['top']} {p['right']} {p['bottom']} {p['left']}"
    t = b["type"]
    if t == "image":
        img = f'<img src="{ctx["img_live"](b.get("src"))}" alt="{b.get("alt","")}" width="{re.sub(r"[^0-9]","",b["width"]) or 600}" style="display:block;width:100%;max-width:{b["width"]};height:auto;border:0;margin:0 auto">'
        if b.get("href"): img = f'<a href="{b["live_href"]}" target="_blank">{img}</a>'
        return f'<div style="{pad};text-align:{b.get("align","center")}">{img}</div>'
    if t == "nav":
        links = "&nbsp;&nbsp;&nbsp;&nbsp;".join(
            f'<a href="{l["live_href"] or "#"}" style="{style_str({k: v for k, v in l["style"].items() if k in ("color","font-family","font-size","font-weight","letter-spacing","text-transform")})};text-decoration:none">{l["text"]}</a>'
            for l in b["links"])
        return f'<div style="{pad};text-align:center;font-family:{ctx["font"]}">{links}</div>'
    if t in ("text", "html"):
        wst = style_str({k: v for k, v in b.get("wrapper_style", {}).items() if k in ("font-family","font-size","font-style","font-weight","letter-spacing","line-height","text-align","color")})
        body = b["live_html"] if t == "html" else normalize_text(b["live_html"], ctx["rules"])
        return f'<div style="{pad};{wst}">{body}</div>'
    if t == "button":
        ip = b["inner_padding"]
        bb = f";border-bottom:{b['border_bottom']}" if b.get("border_bottom") else ""
        st = (f"display:inline-block;background:{b['bg']};color:{b['color']};font-family:{b['font_family']};font-size:{b['font_size']};"
              f"font-weight:{b['font_weight']};letter-spacing:{b['letter_spacing']};line-height:120%;text-decoration:none;"
              f"padding:{ip['top']} {ip['right']} {ip['bottom']} {ip['left']};border-radius:{b['radius']}{bb}")
        return f'<div style="{pad};text-align:{b.get("align","center")}"><a href="{b["live_href"] or "#"}" target="_blank" style="{st}">{b["label"]}</a></div>'
    if t == "divider":
        return f'<div style="{pad}"><div style="border-top:{b["border"]};width:{b["width"]};margin:0 auto;font-size:1px;line-height:1px">&nbsp;</div></div>'
    if t == "spacer":
        return f'<div style="height:{b["height"]};line-height:{b["height"]};font-size:1px">&nbsp;</div>'
    if t == "social":
        icons = "".join(f'<a href="{i["live_href"] or "#"}" target="_blank" style="display:inline-block;margin:0 5px"><img src="{ctx["img_live"](i["src"])}" alt="{i["name"]}" width="{re.sub(r"[^0-9]","",i["width"]) or 32}" style="display:block;border:0"></a>' for i in b["icons"])
        return f'<div style="{pad};text-align:center">{icons}</div>'
    return ""

def build(args):
    model = json.load(open(args.model)); mapping = json.load(open(args.mapping)); meta = json.load(open(args.meta))
    tr = Translator(mapping)
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
           "rules": model["head_rules"], "img": img, "img_live": img, "dims": dims}

    rows_bee, rows_html = [], []
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
            col_bg = next(iter(bgs)) if len(bgs) == 1 and "transparent" not in bgs else None
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
                if own_bg and not col_bg and own_bg.lower() not in (b.get("live_html") or b.get("bee_html") or "").lower():
                    tr.warnings.append(f"A {b['type']} block has background {own_bg} that couldn't be kept (other blocks in its column "
                                       "have none); add it in the Visual Builder if needed")
                mods.append(bee_module(b, ctx))
                hmods.append(html_module(b, ctx))
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
    subject = tr.translate(meta["subject"])
    bee = {"page": {"body": {"container": {"style": {"background-color": model["body_background"]}},
                             "content": {"computedStyle": {"linkColor": model["link_color"], "messageBackgroundColor": "transparent",
                                                          "messageWidth": f"{model['width']}px"},
                                         "style": {"color": "#000000", "font-family": model["default_font"]}},
                             "type": "mailup-bee-page-properties", "webFonts": []},
                    "description": subject, "rows": rows_bee,
                    "template": {"name": "template-base", "type": "basic", "version": "2.0.0"}, "title": meta.get("node_name", "Email")},
           "comments": {}}
    W = model["width"]
    subject = tr.translate(meta["subject"])
    pre = tr.translate(meta.get("preheader") or "")
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
    leftover_cdn = sorted(set(re.findall(r'https://(?:d3k81ch9hvuctc\.cloudfront\.net|[\w.-]*klaviyo[\w.-]*)/[^"\')\s]+', email_html)))
    if leftover_cdn:
        tr.warnings.append(f"{len(leftover_cdn)} image(s) still on Klaviyo's CDN — rehost with import_media_file and add to mapping.image_map")
    if dropped_mobile:
        tr.note(f"dropped {dropped_mobile} mobile-only duplicate block(s) (desktop version kept for all screens)")
    if "#TODO" in email_html or 'href="#"' in email_html:
        tr.warnings.append("Some links are empty ('#') because the Klaviyo source had none — add URLs before sending")

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
        if "event." in email_html:
            tr.errors.append("Email uses trigger-event data (event.*) but meta.trigger is 'now' — set an event trigger")
    payload = {"name": meta["scenario_name"], "nodes": [tnode, node],
               "connections": [{"source": {"node_id": 0, "connector_index": 0}, "destination": {"node_id": 1, "connector_index": 0}}],
               "last_node_id": 1}

    # ---- BEE structural validation (same rules as the email-to-engagement skills)
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

    import os
    os.makedirs(args.out_dir, exist_ok=True)
    json.dump(bee, open(f"{args.out_dir}/bee.json", "w"), ensure_ascii=False)
    open(f"{args.out_dir}/email.html", "w", encoding="utf-8").write(email_html)
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
    ctxd = json.load(open(args.context))
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
    html = open(args.html, encoding="utf-8").read()
    try:
        out = env.from_string(html).render(customer=ctxd.get("customer", {}), event=ctxd.get("event", {}), catalogs=cats,
                                            aggregates=ctxd.get("aggregates", {}),
                                            vouchers=Pools(), project_variables=ctxd.get("project_variables", {}),
                                            consent={"page": "https://consent.example/page"},
                                            email={"view": "https://view.example", "unsubscribe": "https://unsub.example"},
                                            recommendations=lambda *a, **k: recs_items[: (a[1] if len(a) > 1 else 4)],
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
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup"); s.add_argument("--venv", required=True)
    a = sub.add_parser("analyze"); a.add_argument("export"); a.add_argument("--out-dir", required=True)
    b = sub.add_parser("build")
    for f in ("--model", "--mapping", "--meta", "--out-dir"): b.add_argument(f, required=True)
    r = sub.add_parser("render-check"); r.add_argument("--html", required=True); r.add_argument("--context", required=True); r.add_argument("--out")
    for p in (a, b, r): p.add_argument("--venv")
    args = ap.parse_args()
    if args.cmd == "analyze": analyze(args.export, args.out_dir)
    elif args.cmd == "build": build(args)
    else: render_check(args)
