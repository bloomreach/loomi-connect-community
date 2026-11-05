"""Tests for engagement-ab-test-setup's ab_test_duration.py: customers and days an Engagement A/B split needs, for
even and uneven (holdout) splits. All inputs are made up."""
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plugins/loomi-engagement/skills/engagement-ab-test-setup/scripts/ab_test_duration.py"
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("ab_test_duration", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def run(*args, cwd):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", cwd=cwd)


class DurationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_even_split_matches_the_two_proportion_formula(self):
        p, lift, za, zb = 0.04, 0.1, 1.96, 0.8416
        p2 = p * (1 + lift)
        pbar = (p + p2) / 2
        per_bucket = (za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p * (1 - p) + p2 * (1 - p2))) ** 2 / (p2 - p) ** 2
        total = mod.total_needed(p, lift, 0.5, 0.5, za, zb)
        self.assertLessEqual(abs(total - 2 * per_bucket), 1)

    def test_uneven_split_needs_more_customers(self):
        even = mod.total_needed(0.04, 0.1, 0.5, 0.5, 1.96, 0.8416)
        holdout = mod.total_needed(0.04, 0.1, 0.9, 0.1, 1.96, 0.8416)
        self.assertGreater(holdout, 2 * even)

    def test_impossible_lift(self):
        self.assertIsNone(mod.total_needed(0.9, 0.2, 0.5, 0.5, 1.96, 0.8416))

    def test_cli_table_and_out_file(self):
        r = run("--baseline-rate", "0.05", "--entrants", "60000", "--days", "30", "--out", self.dir / "d.json",
                cwd=self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("| +10% |", r.stdout)
        out = json.loads((self.dir / "d.json").read_text(encoding="utf-8"))
        self.assertEqual([row["lift"] for row in out["rows"]], [0.05, 0.1, 0.2])
        self.assertTrue(out["practical"])
        for row in out["rows"]:
            self.assertGreaterEqual(row["recommended_days"], 14)
            self.assertEqual(row["recommended_days"] % 7, 0)
            self.assertGreaterEqual(row["recommended_days"], row["days"])
            self.assertIn(row["control"] + row["variant"], (row["total"], row["total"] + 1))

    def test_too_few_customers_is_called_out(self):
        r = run("--baseline-rate", "0.04", "--entrants", "300", "--days", "30", "--control-share", "90",
                "--variant-share", "10", cwd=self.dir)
        self.assertIn("too few customers", r.stdout)

    def test_bad_inputs(self):
        for args in (("--baseline-rate", "4", "--entrants", "10", "--days", "1"),
                     ("--baseline-rate", "0.04", "--entrants", "10", "--days", "0"),
                     ("--baseline-rate", "0.04", "--entrants", "10", "--days", "7", "--control-share", "60"),
                     ("--baseline-rate", "0.04", "--entrants", "10", "--days", "7", "--control-share", "98",
                      "--variant-share", "2"),
                     ("--baseline-rate", "0.04", "--entrants", "10", "--days", "7", "--relative-lift", "-0.1")):
            with self.subTest(args):
                r = run(*args, cwd=self.dir)
                self.assertEqual(r.returncode, 1)
                self.assertFalse(json.loads(r.stdout)["ok"])

    def test_no_entrants(self):
        r = run("--baseline-rate", "0.04", "--entrants", "0", "--days", "30", cwd=self.dir)
        self.assertEqual(r.returncode, 0)
        self.assertIn("never", r.stdout)


if __name__ == "__main__":
    unittest.main()
