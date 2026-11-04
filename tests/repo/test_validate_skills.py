"""Tests for scripts/validate_skills.py, run against small fake repo trees in a temp folder."""
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "repo" / "minimal"


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_skills", REPO / "scripts" / "validate_skills.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V = load_validator()


class FakeRepoTest(unittest.TestCase):
    """Copies the minimal fixture (one passing plugin with one read-only skill) and points ROOT at it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "repo"
        shutil.copytree(FIXTURE, self.root)
        self.old_root, V.ROOT = V.ROOT, self.root
        self.skill = self.root / "plugins/demo/skills/demo-skill"

    def tearDown(self):
        V.ROOT = self.old_root
        shutil.rmtree(self.tmp)

    def run_validator(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = V.main()
        return code, out.getvalue()

    def edit(self, rel, old, new):
        path = self.root / rel
        text = path.read_text()
        self.assertIn(old, text, f"fixture {rel} lacks {old!r}")
        path.write_text(text.replace(old, new))

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def assertFails(self, fragment):
        code, out = self.run_validator()
        self.assertEqual(code, 1, out)
        self.assertIn(fragment, out)

    def make_writes(self):
        skill = "plugins/demo/skills/demo-skill"
        self.edit(f"{skill}/SKILL.md", "access: read-only", "access: writes")
        self.edit(f"{skill}/README.md", "| **Access** | Read-only |", "| **Access** | **Writes**: creates drafts |")
        self.edit("plugins/demo/README.md", "| Read-only |", "| **Writes** |")
        self.edit(f"{skill}/agents/openai.yaml", "allow_implicit_invocation: true", "allow_implicit_invocation: false")


class TestBaseline(FakeRepoTest):
    def test_fixture_passes(self):
        code, out = self.run_validator()
        self.assertEqual(code, 0, out)
        self.assertIn("Checked 1 skill(s): OK", out)


class TestListings(FakeRepoTest):
    def test_missing_from_plugin_readme(self):
        self.edit("plugins/demo/README.md", "(skills/demo-skill/)", "(skills/other/)")
        self.assertFails("plugins/demo/README.md: does not link to skill 'demo-skill'")

    def test_missing_from_skills_by_task(self):
        self.edit("docs/skills-by-task.md", "skills/demo-skill/", "skills/")
        self.assertFails("docs/skills-by-task.md: does not link to skill 'demo-skill'")


class TestAccess(FakeRepoTest):
    def test_writes_skill_passes_when_consistent(self):
        self.make_writes()
        code, out = self.run_validator()
        self.assertEqual(code, 0, out)

    def test_plugin_readme_access_column_mismatch(self):
        self.edit("plugins/demo/README.md", "| Read-only |", "| **Writes** |")
        self.assertFails("Access column for 'demo-skill' is '**Writes**'")

    def test_skill_readme_access_row_mismatch(self):
        self.edit("plugins/demo/skills/demo-skill/README.md", "| **Access** | Read-only |", "| **Access** | **Writes** |")
        self.assertFails("README.md Access row must start with 'Read-only'")

    def test_skill_readme_missing_access_row(self):
        self.edit("plugins/demo/skills/demo-skill/README.md", "| **Access** | Read-only |\n", "")
        self.assertFails("README.md has no `| **Access** |` row")


class TestWritesPolicy(FakeRepoTest):
    def test_writes_needs_openai_yaml(self):
        self.make_writes()
        (self.skill / "agents/openai.yaml").unlink()
        self.assertFails("`writes` skill needs agents/openai.yaml with `allow_implicit_invocation: false`")

    def test_writes_needs_implicit_invocation_off(self):
        self.make_writes()
        self.edit("plugins/demo/skills/demo-skill/agents/openai.yaml",
                  "allow_implicit_invocation: false", "allow_implicit_invocation: true")
        self.assertFails("`writes` skill needs agents/openai.yaml")


class TestManifests(FakeRepoTest):
    def set_codex(self, **changes):
        path = self.root / "plugins/demo/.codex-plugin/plugin.json"
        data = json.loads(path.read_text())
        data.update(changes)
        path.write_text(json.dumps(data))

    def test_version_differs(self):
        self.set_codex(version="9.9.9")
        self.assertFails("plugins/demo: `version` differs between .claude-plugin/plugin.json and .codex-plugin")

    def test_description_differs(self):
        self.set_codex(description="Something else")
        self.assertFails("`description` differs")

    def test_reported_once_for_both_marketplaces(self):
        self.set_codex(version="9.9.9")
        _, out = self.run_validator()
        self.assertEqual(out.count("`version` differs"), 1, out)


class TestScriptCommands(FakeRepoTest):
    SKILL = "plugins/demo/skills/demo-skill/SKILL.md"
    GOOD = "python3 <this skill's folder>/scripts/demo.py input.json --out result.json"

    def test_relative_scripts_path(self):
        self.edit(self.SKILL, self.GOOD, "python3 scripts/demo.py input.json --out result.json")
        self.assertFails("runs scripts/ by a relative path")

    def test_relative_path_in_inline_code(self):
        self.edit(self.SKILL, "## Steps", "## Steps\n\nRun `python3 scripts/demo.py input.json`.")
        self.assertFails("runs scripts/ by a relative path")

    def test_missing_script(self):
        self.edit(self.SKILL, self.GOOD, self.GOOD.replace("demo.py", "missing.py"))
        self.assertFails("names scripts/missing.py, which is not in this skill's scripts/ folder")

    def test_unknown_flag(self):
        self.edit(self.SKILL, self.GOOD, self.GOOD + " --verbose")
        self.assertFails("passes --verbose, which scripts/demo.py does not define")


class TestSharedScripts(FakeRepoTest):
    def add_copy(self, text):
        other = self.root / "plugins/demo/skills/second-skill"
        shutil.copytree(self.skill, other)
        self.edit("plugins/demo/skills/second-skill/SKILL.md", "name: demo-skill", "name: second-skill")
        self.edit("plugins/demo/README.md", "\n\nTo add", "\n| [second-skill](skills/second-skill/) | x | Read-only |\n\nTo add")
        start = self.root / "docs/skills-by-task.md"
        start.write_text(start.read_text() + "\n[second-skill](../plugins/demo/skills/second-skill/)\n")
        (other / "scripts/demo.py").write_text(text)

    def test_identical_copies_pass(self):
        self.add_copy((self.skill / "scripts/demo.py").read_text())
        code, out = self.run_validator()
        self.assertEqual(code, 0, out)

    def test_different_copies_fail(self):
        self.add_copy((self.skill / "scripts/demo.py").read_text() + "# drift\n")
        self.assertFails("second-skill/scripts/demo.py: differs from plugins/demo/skills/demo-skill/scripts/demo.py")

    def test_allowlist(self):
        self.add_copy((self.skill / "scripts/demo.py").read_text() + "# drift\n")
        V.SHARED_SCRIPT_EXCEPTIONS.add("demo.py")
        try:
            code, out = self.run_validator()
        finally:
            V.SHARED_SCRIPT_EXCEPTIONS.discard("demo.py")
        self.assertEqual(code, 0, out)


class TestLinks(FakeRepoTest):
    def test_broken_relative_link(self):
        self.write("docs/extra.md", "See [nowhere](missing.md#part).\n")
        self.assertFails("docs/extra.md: broken link 'missing.md#part'")

    def test_valid_and_ignored_links(self):
        self.write("docs/extra.md", "\n".join([
            "[start](skills-by-task.md#every-monday) [folder](../plugins/demo/) [web](https://example.com/x)",
            "[mail](mailto:a@example.com) [anchor](#top) ![img](../plugins/demo/README.md)",
            "`[code](not-checked.md)`",
            "```", "[fenced](not-checked.md)", "```",
        ]) + "\n")
        code, out = self.run_validator()
        self.assertEqual(code, 0, out)

    def test_github_route_allowed_only_from_listed_file(self):
        self.write("CONTRIBUTING.md", "[open an issue](../../issues/new/choose)\n")
        code, out = self.run_validator()
        self.assertEqual(code, 0, out)
        self.write("docs/extra.md", "[open an issue](../../issues/new/choose)\n")
        self.assertFails("docs/extra.md: broken link '../../issues/new/choose'")

    def test_skipped_folders(self):
        self.write("node_modules/pkg/README.md", "[x](missing.md)\n")
        self.write(".claude/agents/a.md", "[x](missing.md)\n")
        code, out = self.run_validator()
        self.assertEqual(code, 0, out)


class TestAllowedTools(FakeRepoTest):
    def test_allowed_tools_rejected(self):
        self.edit("plugins/demo/skills/demo-skill/SKILL.md", "license:", "allowed-tools: Read\nlicense:")
        self.assertFails("`allowed-tools` is Claude Code only; leave out of shared skills")


if __name__ == "__main__":
    unittest.main()
