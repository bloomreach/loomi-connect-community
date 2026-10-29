import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plugins" / "loomi-discovery" / "skills" / "discovery-rule-audit" / "scripts" / "audit_rules.py"
FIX = ROOT / "tests" / "fixtures" / "discovery"


def run(*args):
    """Run the script by its full path from a fresh working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp,
                              capture_output=True, text=True, timeout=60)


class AuditRulesTest(unittest.TestCase):
    def test_help(self):
        self.assertEqual(run("--help").returncode, 0)

    def audit(self):
        p = run("--rules", FIX / "ar_ranking_rules.json", "--rules", FIX / "ar_media_rules.json",
                "--queries", FIX / "ar_queries.json", "--today", "2026-10-01")
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def test_media_rule_sharing_an_id_with_a_ranking_rule_is_kept(self):
        out = self.audit()
        self.assertIn("Rules checked: 4 (4 enabled)", out)
        self.assertIn("search media: 1", out)

    def test_rule_expired_by_end_date_is_not_a_duplicate(self):
        out = self.audit()
        self.assertIn("Expired but still switched on", out)
        self.assertNotIn("enabled ranking rules for \"jeans\"", out)

    def test_string_zero_visits_flag_no_searches(self):
        out = self.audit()
        self.assertIn("No searches for \"wellies\"", out)
        self.assertNotIn("No searches for \"jeans\"", out)

    def sync_ab(self, *extra):
        p = run("--rules", FIX / "ar_sync_ab_rules.json", "--today", "2026-10-01", *extra)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def row(self, out, rule_id):
        return [l for l in out.splitlines() if l.startswith("| ") and f"| {rule_id} " in l]

    def test_failed_sync_is_high(self):
        rows = self.row(self.sync_ab(), "901")
        self.assertTrue(any(r.startswith("| high |") and "Sync failed (syncStatus FAILED)" in r for r in rows), rows)

    def test_success_and_expired_sync_not_flagged(self):
        out = self.sync_ab()
        self.assertEqual(out.count("Sync failed"), 1)
        self.assertEqual(self.row(out, "902"), [])
        self.assertFalse(any("Sync failed" in r for r in self.row(out, "903")))

    def test_ab_live_with_running_experiment_skips_other_checks(self):
        rows = self.row(self.sync_ab("--experiments", FIX / "ar_experiments_running.json"), "904")
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("| info |", rows[0])
        self.assertIn("In a RUNNING A/B test", rows[0])

    def test_ab_live_without_running_experiment_is_stuck(self):
        out = self.sync_ab("--experiments", FIX / "ar_experiments_completed.json")
        rows = self.row(out, "904")
        self.assertTrue(any(r.startswith("| medium |") and "A/B test flag stuck" in r for r in rows), rows)
        # Its other checks still run: it is expired but switched on.
        self.assertTrue(any(r.startswith("| high |") and "Expired but still switched on" in r for r in rows), rows)
        self.assertNotIn("In a RUNNING A/B test", out)
        self.assertNotIn("Not checked", out)

    def test_ab_live_without_experiments_says_check_did_not_run(self):
        out = self.sync_ab()
        self.assertIn("Not checked: stuck A/B test flags", out)
        rows = self.row(out, "904")
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("not checked: no experiments list", rows[0])
        self.assertNotIn("A/B test flag stuck", out)

    def test_error_returned_as_data_stops(self):
        for args in (("--rules", FIX / "denied.json"),
                     ("--rules", FIX / "ar_ranking_rules.json", "--queries", FIX / "denied.json")):
            p = run(*args)
            self.assertEqual(p.returncode, 1, args)
            self.assertEqual(p.stdout, "")
            self.assertNotIn("Rules checked: 0", p.stdout)
            self.assertIn("Loomi Connect returned an error: [ACCESS_DENIED]", p.stderr)


if __name__ == "__main__":
    unittest.main()
