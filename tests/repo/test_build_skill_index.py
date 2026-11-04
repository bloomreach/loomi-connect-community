import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "scripts" / "build_skill_index.py"
UPDATE = ROOT / "scripts" / "update_published_tools.py"


def load(path, name):
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = old


def run(script, *args):
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(script), *map(str, args)], cwd=tmp,
                              capture_output=True, text=True, encoding="utf-8")


class BuildSkillIndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = load(BUILD, "build_skill_index")
        cls.data = cls.b.collect(ROOT)

    def test_skills_md_is_up_to_date(self):
        r = run(BUILD, "--check", "--today", "2026-11-04")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def test_every_skill_is_listed_once_with_its_access(self):
        md = self.b.render_markdown(self.data)
        skill_files = sorted(ROOT.glob("plugins/*/skills/*/SKILL.md"))
        self.assertEqual(len(self.data["skills"]), len(skill_files))
        for path in skill_files:
            name, plugin = path.parent.name, path.parts[-4]
            rows = [l for l in md.splitlines() if l.startswith(f"| [{name}](plugins/{plugin}/skills/{name}/)")]
            self.assertEqual(len(rows), 1, name)
            writes = "access: writes" in path.read_text(encoding="utf-8")
            self.assertEqual(rows[0].endswith("| **Writes** |"), writes, name)

    def test_totals_add_up(self):
        counts = self.b.plugin_counts(self.data)
        self.assertEqual(sum(c["skills"] for c in counts.values()), len(self.data["skills"]))
        self.assertEqual(sum(c["writes"] for c in counts.values()), sum(s["writes"] for s in self.data["skills"]))

    def test_tool_list_has_no_internal_tools_and_coverage_uses_it(self):
        self.assertTrue(self.data["tools"])
        self.assertFalse([t for t in self.data["tools"] if "internal" in t["tags"]])
        self.assertTrue(any(t["skills"] for t in self.data["tools"]))

    def test_site_builds_with_every_skill_and_no_email_addresses(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run(BUILD, "--check", "--site", Path(tmp) / "site", "--today", "2026-11-04")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = Path(tmp) / "site"
            for f in ("index.html", "skills.html", "quickstart.html", "tools.html", "assets/bloomreach-logo-icon.svg", "assets/theme.js", ".nojekyll"):
                self.assertTrue((out / f).exists(), f)
            page = (out / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("__DATA__", page)
            self.assertNotIn("__LOGO__", page)
            payload = json.loads(re.search(r"const D=(\{.*?\});\n", page, re.S).group(1))
            self.assertEqual({s["name"] for s in payload["skills"]}, {s["name"] for s in self.data["skills"]})
            self.assertNotRegex(json.dumps(payload["contributors"]), r"@")
            zips = sorted((out / "downloads").glob("*.zip"))
            self.assertEqual({z.stem for z in zips}, {s["name"] for s in self.data["skills"]})
            with zipfile.ZipFile(out / "downloads" / "loomi-project-overview.zip") as z:
                names = z.namelist()
            self.assertIn("loomi-project-overview/SKILL.md", names)
            self.assertFalse([n for n in names if "__pycache__" in n or not n.startswith("loomi-project-overview/")])

    def test_old_tool_list_warns(self):
        self.assertIsNone(self.b.tool_list_age_warning("2026-11-01", dt.date(2026, 11, 4)))
        self.assertIn("days ago", self.b.tool_list_age_warning("2026-09-01", dt.date(2026, 11, 4)))
        self.assertIn("no valid", self.b.tool_list_age_warning(None, dt.date(2026, 11, 4)))


class UpdatePublishedToolsTest(unittest.TestCase):
    def test_writes_sorted_list_without_internal_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "tools.json", Path(tmp) / "out.txt"
            src.write_text(json.dumps({"tools": [
                {"name": "search_scenarios", "tags": ["scenario", "engagement"]},
                {"name": "whoami", "tags": ["debug", "internal"]},
                {"name": "list_projects", "tags": ["engagement", "bootstrap"]}]}), encoding="utf-8")
            r = run(UPDATE, src, "--today", "2026-11-04", "--out", out)
            self.assertEqual(r.returncode, 0, r.stderr)
            lines = out.read_text(encoding="utf-8").splitlines()
            self.assertIn("# checked: 2026-11-04", lines)
            self.assertEqual([l for l in lines if not l.startswith("#")],
                             ["list_projects\tbootstrap,engagement", "search_scenarios\tengagement,scenario"])

    def test_rejects_a_response_without_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "bad.json"
            src.write_text('{"success": false}', encoding="utf-8")
            r = run(UPDATE, src, "--out", Path(tmp) / "out.txt")
            self.assertEqual(r.returncode, 1)
            self.assertIn("no 'tools' list", r.stderr)


if __name__ == "__main__":
    unittest.main()
