#!/usr/bin/env python3
"""Build the skill index: SKILLS.md at the repo root, and the website published to GitHub Pages.

    python3 scripts/build_skill_index.py              # rewrite SKILLS.md
    python3 scripts/build_skill_index.py --check      # fail if SKILLS.md is out of date (CI runs this)
    python3 scripts/build_skill_index.py --site _site # also build the website into _site/

Everything comes from the repo: each skill's SKILL.md frontmatter, the plugin manifests,
docs/published-tools.txt (refreshed with scripts/update_published_tools.py) and, for the
website only, the git history for the contributor list. Never edit SKILLS.md by hand.
Standard library only; no network access.
"""
import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_skills  # noqa: E402  (shared frontmatter parser)

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/bloomreach/loomi-connect-community"
TOOLS_FILE = "docs/published-tools.txt"
TOOL_LIST_MAX_AGE_DAYS = 30
PLUGIN_ORDER = ["loomi-engagement", "loomi-discovery", "loomi-platform", "loomi-product-data"]
TEXT_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ".html", ".txt"}
BOT_EMAILS = {"noreply@anthropic.com"}


def fail(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def first_sentence(text, limit=220):
    text = re.sub(r"\s+", " ", text or "").strip()
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    s = m.group(1) if m else text
    s = re.sub(r",? (?:using|with) Loomi Connect", "", s)
    return s if len(s) <= limit else s[: limit - 1].rsplit(" ", 1)[0] + "…"


def read_tools(root):
    path = root / TOOLS_FILE
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        fail(f"Can't read {TOOLS_FILE}: {e}. Create it with scripts/update_published_tools.py.")
    checked, tools = None, []
    for line in lines:
        if line.startswith("# checked:"):
            checked = line.split(":", 1)[1].strip()
        elif line.strip() and not line.startswith("#"):
            name, _, tags = line.partition("\t")
            tools.append({"name": name.strip(), "tags": [t for t in tags.strip().split(",") if t]})
    return checked, tools


def tool_area(tags):
    areas = [a for a in ("engagement", "discovery", "datahub") if a in tags]
    return areas[0] if len(areas) == 1 else "shared"


def skill_text(skill_dir):
    parts = []
    for f in sorted(skill_dir.rglob("*")):
        if f.is_file() and f.suffix in TEXT_SUFFIXES and "__pycache__" not in f.parts:
            parts.append(f.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def collect(root):
    skills, plugins = [], {}
    for plugin in PLUGIN_ORDER:
        manifest = root / "plugins" / plugin / ".claude-plugin" / "plugin.json"
        try:
            plugins[plugin] = {"name": plugin, "description": json.loads(manifest.read_text(encoding="utf-8"))["description"]}
        except (OSError, ValueError, KeyError) as e:
            fail(f"Can't read {manifest.relative_to(root)}: {e}")
    for path in sorted(root.glob("plugins/*/skills/*/SKILL.md")):
        plugin = path.parts[-4]
        if plugin not in plugins:
            fail(f"{path.relative_to(root)} is in a plugin the index doesn't know about. Add it to PLUGIN_ORDER.")
        fields, _ = validate_skills.parse_frontmatter(path.read_text(encoding="utf-8"))
        meta = (fields or {}).get("metadata") or {}
        skills.append({
            "plugin": plugin,
            "name": fields.get("name", path.parent.name),
            "writes": meta.get("access") == "writes",
            "products": meta.get("products", ""),
            "summary": first_sentence(fields.get("description", "")),
            "text": skill_text(path.parent),
        })
    skills.sort(key=lambda s: (PLUGIN_ORDER.index(s["plugin"]), s["name"]))
    checked, tools = read_tools(root)
    for t in tools:
        pat = re.compile(r"\b" + re.escape(t["name"]) + r"\b")
        t["skills"] = sorted(s["name"] for s in skills if pat.search(s["text"]))
        t["area"] = tool_area(t["tags"])
    for s in skills:
        del s["text"]
    scripts = sorted(p for p in root.glob("plugins/*/skills/*/scripts/*.py"))
    tests = sorted(p for p in root.glob("tests/**/test_*.py"))
    return {"skills": skills, "plugins": plugins, "tools": tools, "tools_checked": checked,
            "scripts": len(scripts), "tests": len(tests)}


def plugin_counts(data):
    by = {p: {"skills": 0, "writes": 0} for p in PLUGIN_ORDER}
    for s in data["skills"]:
        by[s["plugin"]]["skills"] += 1
        by[s["plugin"]]["writes"] += s["writes"]
    return by


def md_cell(text):
    return text.replace("|", "\\|")


def render_markdown(data):
    skills, tools, counts = data["skills"], data["tools"], plugin_counts(data)
    used = [t for t in tools if t["skills"]]
    writes = sum(s["writes"] for s in skills)
    out = [
        "# Skills",
        "",
        "<!-- Generated by scripts/build_skill_index.py from each skill's SKILL.md. Don't edit by hand: run the script. -->",
        "",
        f"**{len(skills)} skills** in **{len(PLUGIN_ORDER)} plugins**. {len(skills) - writes} only read; "
        f"{writes} can change something, and only after you confirm. For skills grouped by the job you're doing, "
        "see [docs/start-here.md](docs/start-here.md).",
        "",
        "| Plugin | Skills | Read-only | Writes |",
        "|---|---:|---:|---:|",
    ]
    for p in PLUGIN_ORDER:
        c = counts[p]
        out.append(f"| [`{p}`](plugins/{p}/) | {c['skills']} | {c['skills'] - c['writes']} | {c['writes']} |")
    out.append(f"| **Total** | **{len(skills)}** | **{len(skills) - writes}** | **{writes}** |")
    out += [
        "",
        f"The skills use {len(used)} of the {len(tools)} published Loomi Connect tools "
        f"(tool list checked {data['tools_checked']}).",
    ]
    unused = [t["name"] for t in tools if not t["skills"]]
    if unused:
        out.append("Not used by any skill yet: " + ", ".join(f"`{n}`" for n in unused) + ".")
    for p in PLUGIN_ORDER:
        out += ["", f"## {p}", "", md_cell(data["plugins"][p]["description"]), "", "| Skill | What it does | Access |", "|---|---|---|"]
        for s in (s for s in skills if s["plugin"] == p):
            access = "**Writes**" if s["writes"] else "Read-only"
            out.append(f"| [{s['name']}](plugins/{p}/skills/{s['name']}/) | {md_cell(s['summary'])} | {access} |")
    return "\n".join(out) + "\n"


def contributors(root):
    """Names from commit authors and Signed-off-by lines, one per email. Emails are never output."""
    try:
        log = subprocess.run(
            ["git", "log", "--format=%an\x1f%ae\x1f%(trailers:key=Signed-off-by,valueonly,separator=\x1e)\x1d"],
            cwd=root, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    names, commits = {}, Counter()
    for entry in log.split("\x1d"):
        if not entry.strip():
            continue
        name, email, trailers = (entry.strip("\n").split("\x1f") + ["", ""])[:3]
        people = [(name, email)]
        for t in trailers.split("\x1e"):
            m = re.match(r"\s*(.+?)\s*<([^>]+)>", t)
            if m:
                people.append((m.group(1), m.group(2)))
        for n, e in people:
            e = e.strip().lower()
            if not e or e in BOT_EMAILS:
                continue
            best = names.get(e, "")
            if (" " in n, len(n)) > (" " in best, len(best)):
                names[e] = n.strip()
        commits[email.strip().lower()] += 1
    order = sorted(names, key=lambda e: (-commits[e], names[e].lower()))
    seen, result = set(), []
    for e in order:
        if names[e].lower() not in seen:
            seen.add(names[e].lower())
            result.append(names[e])
    return result


def inline_svg(path, extra_attrs=""):
    svg = path.read_text(encoding="utf-8")
    svg = re.sub(r"<\?xml[^>]*>\s*", "", svg)
    return svg.replace("<svg ", f"<svg {extra_attrs} ", 1)


def render_site(root, data, outdir):
    site = root / "site"
    counts = plugin_counts(data)
    payload = {
        "skills": data["skills"],
        "plugins": [dict(data["plugins"][p], **counts[p]) for p in PLUGIN_ORDER],
        "tools": [{"name": t["name"], "area": t["area"], "skills": t["skills"]} for t in data["tools"]],
        "toolsChecked": data["tools_checked"],
        "scripts": data["scripts"],
        "tests": data["tests"],
        "contributors": contributors(root),
        "repo": REPO_URL,
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    logo = (inline_svg(site / "assets" / "bloomreach-logo-icon.svg", 'class="logo-icon" aria-hidden="true" focusable="false"')
            + inline_svg(site / "assets" / "bloomreach-logo-text.svg",
                         'class="logo-text" role="img" aria-label="Bloomreach" fill="currentColor"'))
    outdir.mkdir(parents=True, exist_ok=True)
    for name in ("index", "skills"):
        try:
            tpl = (site / f"{name}.template.html").read_text(encoding="utf-8")
        except OSError as e:
            fail(f"Can't read site/{name}.template.html: {e}")
        page = tpl.replace("__DATA__", blob).replace("__LOGO__", logo)
        (outdir / f"{name}.html").write_text(page, encoding="utf-8", newline="\n")
    shutil.copytree(site / "assets", outdir / "assets", dirs_exist_ok=True)
    (outdir / ".nojekyll").write_text("", encoding="utf-8")


def tool_list_age_warning(checked, today):
    try:
        age = (today - dt.date.fromisoformat(checked)).days
    except (TypeError, ValueError):
        return f"warning: {TOOLS_FILE} has no valid '# checked:' date."
    if age > TOOL_LIST_MAX_AGE_DAYS:
        return (f"warning: {TOOLS_FILE} was checked {age} days ago. Refresh it: call list_all_tools in a session "
                "with Loomi Connect, save the response, and run scripts/update_published_tools.py.")
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="fail if SKILLS.md is out of date instead of rewriting it")
    ap.add_argument("--site", metavar="DIR", help="also build the website into DIR (for GitHub Pages)")
    ap.add_argument("--root", default=str(ROOT), help="repo root (default: this repo)")
    ap.add_argument("--today", help="today's date, YYYY-MM-DD, for the tool-list age warning (default: today, UTC)")
    a = ap.parse_args()
    root = Path(a.root).resolve()
    data = collect(root)
    text = render_markdown(data)
    target = root / "SKILLS.md"
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(dt.timezone.utc).date()
    warning = tool_list_age_warning(data["tools_checked"], today)
    if warning:
        print(warning, file=sys.stderr)
    if a.check:
        try:
            current = target.read_text(encoding="utf-8")
        except OSError:
            current = None
        if current != text:
            fail("SKILLS.md is out of date. Run: python3 scripts/build_skill_index.py")
        print(f"SKILLS.md is up to date ({len(data['skills'])} skills).")
    else:
        try:
            target.write_text(text, encoding="utf-8", newline="\n")
        except OSError as e:
            fail(f"Can't write SKILLS.md: {e}")
        print(f"Wrote SKILLS.md ({len(data['skills'])} skills).")
    if a.site:
        render_site(root, data, Path(a.site))
        print(f"Built the website in {a.site}.")


if __name__ == "__main__":
    main()
