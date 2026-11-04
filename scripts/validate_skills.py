#!/usr/bin/env python3
"""Validate every skill in this repo against the Agent Skills spec and our contribution rules.

Uses only the standard library so it runs anywhere. Frontmatter parsing is
deliberately simple: top-level `key: value` pairs plus one level of `metadata:`.

ROOT is a module variable so tests can point the checks at a fake repo tree.
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_GLOBS = ["plugins/*/skills/*/SKILL.md", "templates/*/SKILL.md"]
SPEC_FIELDS = {"name", "description", "license", "compatibility", "metadata"}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ACCESS_VALUES = {"read-only", "writes"}
ACCESS_LABELS = {"read-only": "Read-only", "writes": "**Writes**"}
PRODUCT_VALUES = {"engagement", "discovery", "datahub"}
MAX_BODY_LINES = 500
# Script file names that may differ between skills on purpose, e.g. {"grid_positions.py"}.
SHARED_SCRIPT_EXCEPTIONS = set()
# GitHub web routes that only resolve on github.com, as (file, link) pairs.
GITHUB_ROUTE_LINKS = {
    ("CONTRIBUTING.md", "../../issues/new/choose"),
    ("SECURITY.md", "../../security/advisories/new"),
}
SKIP_DIRS = {".git", "node_modules", ".claude"}


def parse_frontmatter(text):
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 4)
    if end == -1:
        return None, text
    raw, body = text[4:end], text[end + 4:]
    fields, current = {}, None
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")):
            if current is None:
                raise ValueError(f"indented line outside a mapping: {line!r}")
            k, _, v = line.strip().partition(":")
            fields[current][k.strip()] = v.strip().strip('"\'')
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if v:
            fields[k], current = v.strip('"\''), None
        else:
            fields[k], current = {}, k
    return fields, body


FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
PY_RE = re.compile(r"\bpython3?\s")
COMMAND_RULES = [
    (re.compile(r"\\$|\\ "), "continues over several lines"),
    (re.compile(r"python3?\s+-"), "passes flags to Python before the script"),
    (re.compile(r"[;`]|\$\(|\$\w"), "uses ;, backticks, $(...) or a shell variable"),
    (re.compile(r"(^|\s)\w+=\S*\s*(;|&&)"), "sets a shell variable"),
    (re.compile(r"(^|\s)[<>]{1,2}\s*\S"), "uses a redirect"),
    (re.compile(r"\|\|"), "uses ||"),
]
SCRIPT_REF_RE = re.compile(r"(\S*)\bscripts/([\w.-]+\.py)\b")
FLAG_RE = re.compile(r"(?<![\w-])--[A-Za-z][\w-]*")


def documented_commands(body):
    """Script commands a SKILL.md tells the assistant to run: fenced lines and inline code that call python."""
    cmds = []
    for block in FENCE_RE.findall(body):
        cmds += [line.strip() for line in re.sub(r"\\\n\s*", "\\ ", block).splitlines() if PY_RE.search(line.strip())]
    outside = FENCE_RE.sub("", body)
    cmds += [m.strip() for m in re.findall(r"`([^`\n]*\bpython3?\s[^`\n]*)`", outside)]
    # <placeholders> are fine in the docs; they aren't shell redirects.
    return [re.sub(r"<[^<>]+>", "x", c) for c in cmds]


def command_problem(cmd):
    for rule, problem in COMMAND_RULES:
        if rule.search(cmd):
            return problem
    return None


def script_command_problems(cmd, skill_dir):
    """Problems with the script a command runs: relative path, missing file, or unknown --flags."""
    m = SCRIPT_REF_RE.search(cmd)
    if not m:
        return []
    short, (prefix, script) = cmd[:80], m.groups()
    if not prefix:
        return [f"script command {short!r} runs scripts/ by a relative path; give the full path, "
                "e.g. `<this skill's folder>/scripts/`; see docs/skill-authoring.md#scripts"]
    source = skill_dir / "scripts" / script
    # The template's example command names a placeholder script.
    if skill_dir.parent.name == "templates":
        return []
    if not source.is_file():
        return [f"script command {short!r} names scripts/{script}, which is not in this skill's scripts/ folder"]
    code = source.read_text(encoding="utf-8", errors="ignore")
    return [f"script command {short!r} passes {flag}, which scripts/{script} does not define"
            for flag in dict.fromkeys(FLAG_RE.findall(cmd)) if flag not in code]


def check_skill(path):
    errors = []
    rel = path.relative_to(ROOT)
    text = path.read_text(encoding="utf-8")
    try:
        fm, body = parse_frontmatter(text)
    except ValueError as e:
        return [f"{rel}: bad frontmatter: {e}"]
    if fm is None:
        return [f"{rel}: missing YAML frontmatter"]

    name = fm.get("name", "")
    if not name:
        errors.append("missing `name`")
    elif not NAME_RE.fullmatch(name) or len(name) > 64:
        errors.append(f"`name` {name!r} must be 1-64 chars of a-z, 0-9 and single hyphens")
    elif name != path.parent.name:
        errors.append(f"`name` {name!r} must match folder name {path.parent.name!r}")
    if re.search(r"claude|anthropic", name):
        errors.append("`name` must not contain 'claude' or 'anthropic'")

    desc = fm.get("description", "")
    if not desc:
        errors.append("missing `description`")
    elif len(desc) > 1024:
        errors.append(f"`description` is {len(desc)} chars (max 1024)")
    elif re.search(r"[<>]", desc):
        errors.append("`description` must not contain < or >")

    if "allowed-tools" in fm:
        errors.append("`allowed-tools` is Claude Code only; leave out of shared skills; "
                      "see docs/skill-authoring.md#client-specific-fields")
    extra = set(fm) - SPEC_FIELDS - {"allowed-tools"}
    if extra:
        errors.append(f"non-portable frontmatter fields {sorted(extra)}; see docs/skill-authoring.md")

    meta = fm.get("metadata")
    access = None
    if not isinstance(meta, dict):
        errors.append("missing `metadata` block")
    else:
        for key in ("author", "version", "products", "access"):
            if not meta.get(key):
                errors.append(f"missing `metadata.{key}`")
        if meta.get("access") and meta["access"] not in ACCESS_VALUES:
            errors.append(f"`metadata.access` must be one of {sorted(ACCESS_VALUES)}")
        else:
            access = meta.get("access")
        products = {p.strip() for p in meta.get("products", "").split(",") if p.strip()}
        if products - PRODUCT_VALUES:
            errors.append(f"unknown `metadata.products` {sorted(products - PRODUCT_VALUES)}")

    if access == "writes":
        yaml = path.parent / "agents" / "openai.yaml"
        yaml_text = yaml.read_text(encoding="utf-8") if yaml.exists() else ""
        if not re.search(r"^\s*allow_implicit_invocation:\s*false\b", yaml_text, re.M):
            errors.append("`writes` skill needs agents/openai.yaml with `allow_implicit_invocation: false`; "
                          "see docs/skill-authoring.md#writes")

    if body.count("\n") > MAX_BODY_LINES:
        errors.append(f"SKILL.md body is over {MAX_BODY_LINES} lines; move detail into references/")

    for f in path.parent.rglob("*"):
        if f.is_file() and f.suffix in {".md", ".yaml", ".yml", ".py", ".sh", ".json"}:
            if "mcp__" in f.read_text(encoding="utf-8", errors="ignore"):
                errors.append(f"{f.relative_to(path.parent)} hard-codes an `mcp__` tool prefix; use plain tool names")

    for cmd in documented_commands(body):
        problem = command_problem(cmd)
        if problem:
            errors.append(f"script command {cmd[:80]!r} {problem}; see docs/skill-authoring.md#scripts")
        errors += script_command_problems(cmd, path.parent)
    if (path.parent / "scripts").is_dir() and "### Running the scripts" not in body:
        errors.append("has scripts/ but no 'Running the scripts' subsection; see docs/skill-authoring.md#scripts")

    readme = path.parent / "README.md"
    if not readme.exists():
        errors.append("missing README.md")
    elif access:
        label = ACCESS_LABELS[access]
        row = re.search(r"^\|\s*\*\*Access\*\*\s*\|\s*(.*)$", readme.read_text(encoding="utf-8"), re.M)
        if not row:
            errors.append("README.md has no `| **Access** |` row; see docs/skill-authoring.md")
        elif not row.group(1).startswith(label):
            errors.append(f"README.md Access row must start with {label!r} to match `metadata.access: {access}`")

    return [f"{rel}: {e}" for e in errors]


def check_manifests():
    errors, compared = [], set()
    for rel in [".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"]:
        try:
            data = json.loads((ROOT / rel).read_text())
        except Exception as e:
            errors.append(f"{rel}: {e}")
            continue
        for p in data.get("plugins", []):
            src = p["source"] if isinstance(p["source"], str) else p["source"].get("path", "")
            plugin_dir = ROOT / src
            found = {}
            for manifest in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
                m = plugin_dir / manifest
                if not m.exists():
                    errors.append(f"{rel}: plugin {p['name']!r} is missing {src}/{manifest}")
                    continue
                found[manifest] = json.loads(m.read_text())
                if found[manifest].get("name") != p["name"]:
                    errors.append(f"{src}/{manifest}: name does not match marketplace entry {p['name']!r}")
            if len(found) == 2 and plugin_dir.resolve() not in compared:
                compared.add(plugin_dir.resolve())
                claude, codex = found.values()
                for key in ("name", "version", "description"):
                    if claude.get(key) != codex.get(key):
                        errors.append(f"{src}: `{key}` differs between .claude-plugin/plugin.json "
                                      "and .codex-plugin/plugin.json")
    return errors


def read_text(rel):
    path = ROOT / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def check_listings():
    """Every plugin skill is linked from its plugin README and docs/skills-by-task.md, with the right Access label."""
    errors = []
    start = read_text("docs/skills-by-task.md")
    for skill_md in sorted(ROOT.glob("plugins/*/skills/*/SKILL.md")):
        skill, plugin = skill_md.parent.name, skill_md.parent.parent.parent.name
        link = f"skills/{skill}/"
        readme_rel = f"plugins/{plugin}/README.md"
        readme = read_text(readme_rel)
        if link not in readme:
            errors.append(f"{readme_rel}: does not link to skill {skill!r} ({link}); see CONTRIBUTING.md")
        if link not in start:
            errors.append(f"docs/skills-by-task.md: does not link to skill {skill!r} ({link}); see CONTRIBUTING.md")
        try:
            fm, _ = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        except ValueError:
            continue  # reported by check_skill
        meta = (fm or {}).get("metadata")
        access = meta.get("access") if isinstance(meta, dict) else None
        row = next((l for l in readme.splitlines() if l.lstrip().startswith("|") and f"({link})" in l), None)
        if row and access in ACCESS_LABELS:
            cell = row.strip().strip("|").split("|")[-1].strip()
            if cell != ACCESS_LABELS[access]:
                errors.append(f"{readme_rel}: Access column for {skill!r} is {cell!r}, but "
                              f"`metadata.access: {access}` needs {ACCESS_LABELS[access]!r}")
    return errors


def check_shared_scripts():
    """Scripts copied into several skills under the same name must stay byte-identical."""
    errors, by_name = [], {}
    for f in sorted(ROOT.glob("plugins/*/skills/*/scripts/*.py")):
        by_name.setdefault(f.name, []).append(f)
    for name, files in sorted(by_name.items()):
        if name in SHARED_SCRIPT_EXCEPTIONS:
            continue
        first = files[0].read_bytes()
        for other in files[1:]:
            if other.read_bytes() != first:
                errors.append(f"{other.relative_to(ROOT)}: differs from {files[0].relative_to(ROOT)}; "
                              "copies of a shared script must be identical")
    return errors


LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^)]*)?\)")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def check_links():
    """Relative links in Markdown files must resolve to a file or folder in the repo."""
    errors, files = [], []
    for folder, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        files += [Path(folder) / n for n in names if n.endswith(".md")]
    for md in sorted(files):
        rel = md.relative_to(ROOT)
        text = INLINE_CODE_RE.sub("", FENCE_RE.sub("", md.read_text(encoding="utf-8")))
        for target in LINK_RE.findall(text):
            if re.match(r"[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
                continue  # http(s), mailto and in-page anchors
            path = target.split("#", 1)[0]
            if (rel.as_posix(), path) in GITHUB_ROUTE_LINKS:
                continue
            if not (md.parent / path).exists():
                errors.append(f"{rel}: broken link {target!r}")
    return errors


def main():
    skills = sorted(p for g in SKILL_GLOBS for p in ROOT.glob(g))
    errors = check_manifests()
    for s in skills:
        errors += check_skill(s)
    errors += check_listings() + check_shared_scripts() + check_links()
    for e in errors:
        print(f"ERROR {e}")
    print(f"Checked {len(skills)} skill(s): {'FAILED' if errors else 'OK'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
