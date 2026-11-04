import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/engagement-repeat-purchase-cohorts"
SCRIPT = SKILL / "scripts/cohort_matrix.py"
FX = ROOT / "tests/fixtures/engagement/engagement-repeat-purchase-cohorts"
CUTOFFS = "2025-02-01,2025-03-01,2025-04-01,2025-04-15"


def run(*args, cwd=None):
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              cwd=cwd or tmp, capture_output=True, text=True, encoding="utf-8")


def summary(*args):
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args), "--out", "s.json"],
                           cwd=tmp, capture_output=True, text=True, encoding="utf-8")
        if r.returncode:
            raise AssertionError(r.stderr)
        return json.loads((Path(tmp) / "s.json").read_text(encoding="utf-8")), r.stdout


class CohortMatrixTest(unittest.TestCase):
    def test_help(self):
        self.assertEqual(run("--help").returncode, 0)

    def test_matrix_offsets_and_partial_cells(self):
        s, out = summary(FX / "matrix_response.json", "--cutoffs", CUTOFFS)
        jan, feb, mar = s["cohorts"]
        self.assertEqual(jan["cohort"], "2025-01")
        self.assertEqual(sorted(jan["cumulative"]), ["0", "1", "2"])
        self.assertAlmostEqual(jan["cumulative"]["2"]["rate"], 0.26)
        # The February row's first cutoff (1 February) is before its month ends, so it's ignored.
        self.assertEqual(sorted(feb["cumulative"]), ["0", "1"])
        self.assertEqual(feb["size"], 500)  # counts given as strings are read
        self.assertEqual(jan["partial"], [{"cutoff": "2025-04-15", "days_after_period": 73, "repeaters": 280, "rate": 0.28}])
        self.assertTrue(mar["small"])
        self.assertIn("Cohort 2025-03 has 50 customers", " ".join(s["warnings"]))

    def test_pooled_curve_chains_cohorts(self):
        s, _ = summary(FX / "matrix_response.json", "--cutoffs", CUTOFFS)
        m0, m1, m2 = s["curve"]
        self.assertEqual((m0["cohorts"], m0["customers"]), (3, 1550))
        self.assertAlmostEqual(m0["second_orders_share"], 125 / 1550)
        self.assertAlmostEqual(m0["rate_per_period"], 125 / 1550 / 0.5)
        self.assertEqual((m1["cohorts"], m1["customers"]), (2, 1500))
        self.assertAlmostEqual(m1["second_orders_share"], 180 / 1500)
        self.assertEqual(m2["cohorts"], 1)
        self.assertAlmostEqual(m2["cumulative_rate"], 125 / 1550 + 0.12 + 0.06)

    def test_quartiles_peak_and_drop(self):
        s, out = summary(FX / "matrix_response.json", "--cutoffs", CUTOFFS)
        self.assertEqual(s["time_to_second_order_days"], {"p25": 12, "median": 28, "p75": 44})
        self.assertEqual(s["peak"]["offset"], 0)
        self.assertEqual(s["drop"]["offset"], 2)
        self.assertEqual(s["drop"]["from_days"], 46)
        self.assertIn("median day 28", out)

    def test_drop_share_override(self):
        s, _ = summary(FX / "matrix_response.json", "--cutoffs", CUTOFFS, "--drop-share", "0.3")
        self.assertIsNone(s["drop"])

    def test_weekly_cohort_uses_pace_per_week(self):
        s, out = summary(FX / "cohorts_week.json")
        self.assertEqual(s["period"], "week")
        self.assertEqual([b["offset"] for b in s["curve"]], [0, 1, 3, 7])
        # W3 covers two weeks: 4% of the cohort in two weeks is 2% a week, half the W1 peak.
        self.assertEqual(s["peak"]["offset"], 1)
        self.assertEqual(s["drop"]["offset"], 3)
        self.assertAlmostEqual(s["curve"][2]["rate_per_period"], 0.02)
        self.assertIn("by the end of week k", out)

    def test_data_end_drops_later_cutoffs(self):
        s, _ = summary(FX / "matrix_response.json", "--cutoffs", CUTOFFS, "--data-end", "2025-04-01")
        self.assertEqual(s["cohorts"][0]["partial"], [])
        self.assertIn("after the data end", " ".join(s["warnings"]))

    def test_falling_counts_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "c.json").write_text(json.dumps({
                "cutoffs": ["2025-02-01", "2025-03-01"],
                "cohorts": [{"start": "2025-01", "size": 300, "repeaters": [50, 40]}]}), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), "c.json"], cwd=tmp, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("repeaters fall from 50 to 40", r.stdout)

    def test_time_zone_shifted_headers_round_to_the_month(self):
        data = json.loads((FX / "matrix_response.json").read_text(encoding="utf-8"))
        data["data"]["rows"][3]["headers"][0]["value"] = 1740783600  # 23:00 UTC the day before 1 March
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "m.json").write_text(json.dumps(data), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), "m.json", "--cutoffs", CUTOFFS],
                               cwd=tmp, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("2025-03 ", r.stdout)
        self.assertNotIn("doesn't start on the 1st", r.stdout)

    def run_with_march_header(self, value):
        data = json.loads((FX / "matrix_response.json").read_text(encoding="utf-8"))
        data["data"]["rows"][3]["headers"][0]["value"] = value
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "m.json").write_text(json.dumps(data), encoding="utf-8")
            return subprocess.run([sys.executable, str(SCRIPT), "m.json", "--cutoffs", CUTOFFS, "--out", "s.json"],
                                  cwd=tmp, capture_output=True, text=True, encoding="utf-8"), \
                json.loads((Path(tmp) / "s.json").read_text(encoding="utf-8")) if (Path(tmp) / "s.json").exists() else None

    def test_utc_plus_13_header_stays_in_its_month(self):
        # 1 March 2025 at local midnight in UTC+13 is 11:00 UTC on 28 February.
        r, s = self.run_with_march_header(1740740400)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c["cohort"] for c in s["cohorts"]], ["2025-01", "2025-02", "2025-03"])
        self.assertEqual(sorted(s["cohorts"][2]["cumulative"]), ["0"])  # 1 April is the end of month 0
        self.assertEqual(s["cohorts"][2]["partial"][0]["days_after_period"], 14)
        self.assertNotIn("doesn't start on the 1st", r.stdout)

    def test_utc_plus_14_and_minus_10_headers_stay_in_their_month(self):
        for value in (1740736800, 1740823200):  # 1 March local midnight in UTC+14 and in UTC-10
            r, s = self.run_with_march_header(value)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(s["cohorts"][2]["cohort"], "2025-03", value)
            self.assertNotIn("doesn't start on the 1st", r.stdout)

    def test_unparseable_size_is_missing_not_zero(self):
        data = json.loads((FX / "matrix_response.json").read_text(encoding="utf-8"))
        data["data"]["rows"][2]["values"][0] = "NA"
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "m.json").write_text(json.dumps(data), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), "m.json", "--cutoffs", CUTOFFS, "--out", "s.json"],
                               cwd=tmp, capture_output=True, text=True, encoding="utf-8")
            s = json.loads((Path(tmp) / "s.json").read_text(encoding="utf-8"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c["cohort"] for c in s["cohorts"]], ["2025-01", "2025-03"])
        self.assertIn("Cohort 2025-02: the cohort size is missing", " ".join(s["warnings"]))

    def test_bad_input_names_the_file_without_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.json").write_text("{not json", encoding="utf-8")
            (Path(tmp) / "c.json").write_text(json.dumps({"cohorts": [{"start": "2025-13", "size": 5, "repeaters": []}]}),
                                              encoding="utf-8")
            cases = [(["bad.json"], "bad.json: not valid JSON"),
                     (["missing.json"], "missing.json: can't read the file"),
                     (["c.json"], "c.json: can't read the date"),
                     ([str(FX / "matrix_response.json"), "--cutoffs", "2025-02-30"], "--cutoffs: can't read the date"),
                     ([str(FX / "matrix_response.json"), "--cutoffs", CUTOFFS, "--out", "no/such/dir/s.json"],
                      "no/such/dir/s.json: can't write the file")]
            for args, msg in cases:
                r = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=tmp, capture_output=True, text=True,
                                   encoding="utf-8")
                self.assertEqual(r.returncode, 1, args)
                self.assertIn(msg, r.stderr)
                self.assertNotIn("Traceback", r.stderr)

    def test_raw_response_needs_cutoffs(self):
        r = run(FX / "matrix_response.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--cutoffs", r.stderr)

    def test_wrong_number_of_cutoffs(self):
        r = run(FX / "matrix_response.json", "--cutoffs", "2025-02-01,2025-03-01")
        self.assertEqual(r.returncode, 1)
        self.assertIn("expected 1 cohort size + 2 cutoffs", r.stderr)

    def test_error_response(self):
        r = run(ROOT / "tests/fixtures/engagement/denied.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Loomi Connect returned an error: [ACCESS_DENIED]", r.stderr)

    def test_example_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            ex = subprocess.run([sys.executable, str(SCRIPT), "--example"], cwd=tmp, capture_output=True, text=True, encoding="utf-8")
            (Path(tmp) / "e.json").write_text(ex.stdout, encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), "e.json"], cwd=tmp, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Pooled curve", r.stdout)

    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
