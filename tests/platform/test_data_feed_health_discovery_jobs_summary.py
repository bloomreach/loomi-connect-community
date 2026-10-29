import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plugins/loomi-platform/skills/data-feed-health/scripts/discovery_jobs_summary.py"
FIX = ROOT / "tests/fixtures/platform/data_feed"
REFS = SCRIPT.parent.parent / "references"


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp,
                              capture_output=True, text=True)


class DiscoveryJobsSummaryTest(unittest.TestCase):
    def test_help(self):
        self.assertEqual(run("--help").returncode, 0)

    def test_access_denied_is_an_error_not_red(self):
        p = run(FIX / "jobs_denied.json")
        self.assertEqual(p.returncode, 1)
        out = json.loads(p.stdout)
        self.assertFalse(out["ok"])
        self.assertIn("Loomi Connect returned an error: [ACCESS_DENIED]", out["error"])
        self.assertNotIn("status", out)

    def test_date_only_now_and_naive_timestamps_are_utc(self):
        p = run("--now", "2026-10-26", FIX / "jobs_naive.json")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["now"], "2026-10-26T00:00:00+00:00")
        self.assertEqual(out["kinds"]["index:update"]["hours_since_success"], 21.5)
        self.assertEqual(out["kinds"]["feed:products"]["hours_since_success"], 22.7)
        self.assertEqual(out["status"], "green")

    def test_bad_now_is_a_clear_error(self):
        p = run("--now", "yesterday", FIX / "jobs_naive.json")
        self.assertEqual(p.returncode, 2)
        self.assertNotIn("Traceback", p.stderr)

    def test_contract_fixture_matches_the_script(self):
        """contract/expected.json is what apps that port these rules test against, so it must stay the script's output."""
        c = FIX / "contract"
        expected = json.loads((c / "expected.json").read_text())
        names = sorted(k for k in expected if k != "now")
        self.assertEqual(names, sorted(f.name for f in c.glob("jobs_*.json")))
        self.assertEqual({expected[n]["status"] for n in names}, {"red", "amber", "green"})
        for name in names:
            p = run("--now", expected["now"], c / name)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout), expected[name],
                             f"the rules changed: regenerate tests/fixtures/platform/data_feed/contract/expected.json ({name})")

    def test_rules_file_is_complete(self):
        rules = json.loads((REFS / "rules.json").read_text())
        keys = set(rules) - {"about", "notes"}
        self.assertEqual(set(rules["notes"]), keys)
        self.assertTrue(all(isinstance(v, str) and v for v in rules["notes"].values()))
        doc = (REFS / "rag-thresholds.md").read_text()
        self.assertEqual([k for k in sorted(keys) if f"`{k}`" not in doc], [],
                         "references/rag-thresholds.md should explain every rule in rules.json by name")

    def test_pixel_fixes_are_well_formed(self):
        fixes = json.loads((REFS / "pixel-fixes.json").read_text())
        self.assertEqual(set(fixes), {"about", "issues", "fallback_fix"})
        self.assertTrue(isinstance(fixes["fallback_fix"], str) and fixes["fallback_fix"].strip())
        self.assertTrue(fixes["issues"])
        for key, v in fixes["issues"].items():
            self.assertRegex(key, r"^[a-z0-9]+(_[a-z0-9]+)*$", "issue keys are Loomi's snake_case status_key")
            self.assertEqual(set(v), {"meaning", "fix"}, key)
            self.assertTrue(all(isinstance(s, str) and s.strip() for s in v.values()), key)


if __name__ == "__main__":
    unittest.main()
