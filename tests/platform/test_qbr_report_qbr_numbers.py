import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plugins/loomi-platform/skills/qbr-report/scripts/qbr_numbers.py"
FIX = ROOT / "tests/fixtures/platform/qbr_report"
C = FIX / "contract"


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp,
                              capture_output=True, text=True, encoding="utf-8")


def ok(*args):
    p = run(*args)
    assert p.returncode == 0, p.stderr + p.stdout
    return json.loads(p.stdout)


CONTRACT_ARGS = [
    "--qoq", f"overall={C / 'qoq_overall.json'}", "--qoq", f"search={C / 'qoq_search.json'}",
    "--qoq", f"category={C / 'qoq_category.json'}", "--qoq", f"desktop={C / 'qoq_desktop.json'}",
    "--qoq", f"mobile={C / 'qoq_mobile.json'}", "--qoq", f"tablet={C / 'qoq_tablet.json'}",
    "--yoy", f"overall={C / 'yoy_overall.json'}", "--yoy", f"search={C / 'yoy_search.json'}",
    "--yoy", f"category={C / 'yoy_category.json'}",
    "--queries", C / "queries.json", "--dead-ends", C / "dead_ends.json", "--categories", C / "categories.json",
    "--products", C / "products.json", "--brands", C / "brands.json", "--experiments", C / "experiments.json",
    "--rules", f"search ranking={C / 'ranking_rules.json'}", "--rules", f"redirects={C / 'redirects.json'}",
    "--start", "2025-07-01", "--end", "2025-09-30",
]


class QbrNumbersTest(unittest.TestCase):
    def test_help(self):
        self.assertEqual(run("--help").returncode, 0)

    def test_contract_fixture_matches_the_script(self):
        """contract/expected.json pins the rules: changing one means regenerating it on purpose."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "qbr.json"
            p = run(*CONTRACT_ARGS, "--out", target)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")),
                             json.loads((C / "expected.json").read_text(encoding="utf-8")),
                             "the rules changed: regenerate tests/fixtures/platform/qbr_report/contract/expected.json")

    def test_three_way_kpis_from_raw_counts(self):
        o = ok(*CONTRACT_ARGS)["kpis"]["overall"]
        self.assertEqual(o["this_quarter"]["rpv"], 12.0)
        self.assertEqual(o["this_quarter"]["aov"], 240.0)
        self.assertEqual(o["vs_previous_quarter"]["revenue_pct"], 20.0)
        self.assertEqual(o["vs_previous_quarter"]["conversion_pts"], 0.22)
        self.assertEqual(o["same_quarter_last_year"]["revenue"], 1100000.0)
        self.assertEqual(o["vs_same_quarter_last_year"]["revenue_pct"], 9.09)

    def test_other_and_devices(self):
        k = ok(*CONTRACT_ARGS)["kpis"]
        self.assertEqual(k["other"]["revenue"], 300000.0)
        self.assertEqual(k["other"]["vs_same_quarter_last_year_pct"], 20.0)
        self.assertEqual(k["devices_cover_overall_pct"], 100.0)
        self.assertEqual(k["share_of_revenue_change_pct"], {"search": 25.0, "category": 10.0, "other": 65.0})

    def test_no_data_last_year_is_not_minus_100(self):
        o = ok("--qoq", f"overall={C / 'qoq_overall.json'}", "--yoy", f"overall={FIX / 'yoy_overall_nodata.json'}")
        o = o["kpis"]["overall"]
        self.assertIsNone(o["vs_same_quarter_last_year"])
        self.assertIn("no data", o["note_last_year"])

    def test_mismatched_dates_warn(self):
        out = ok("--qoq", f"overall={C / 'qoq_overall.json'}", "--yoy", f"overall={FIX / 'yoy_overall_other_dates.json'}")
        self.assertIn("covered different dates", out["warnings"][0])

    def test_issues_and_dead_ends(self):
        t = ok(*CONTRACT_ARGS)["top_and_issues"]
        self.assertEqual(t["searches"]["issues"][0]["name"], "query 09")
        self.assertEqual(t["searches"]["dead_ends"]["count"], 2)
        self.assertEqual(t["categories"]["issues"][0]["name"], "Category 12")
        self.assertIn("vs previous quarter", t["categories"]["issues"][0]["reasons"][0])

    def test_work_done_uses_start_and_end_not_modified(self):
        w = ok(*CONTRACT_ARGS)["work_done"]
        names = [e["name"] for e in w["experiments"]["list"]]
        self.assertEqual(names, ["Spanning test", "Search ranking test: boots", "Category grid test"])
        self.assertEqual(w["experiments"]["still_running"], 1)
        self.assertEqual(w["rules"]["search ranking"], {"listed": 4, "created_in_quarter": 1, "changed_in_quarter": 1,
                                                        "enabled_now": 3, "expired_but_enabled": 1})

    def test_never_outputs_editor_emails(self):
        self.assertNotIn("@", json.dumps(ok(*CONTRACT_ARGS)))

    def test_work_done_needs_dates(self):
        p = run("--experiments", C / "experiments.json")
        self.assertEqual(p.returncode, 1)
        self.assertIn("--start", json.loads(p.stdout)["error"])

    def test_bad_card_name(self):
        p = run("--qoq", f"phone={C / 'qoq_overall.json'}")
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn("Traceback", p.stderr)

    def test_error_response_stops(self):
        p = run("--qoq", f"overall={FIX / 'denied.json'}")
        self.assertEqual(p.returncode, 1)
        self.assertNotIn("Traceback", p.stderr)
        self.assertIn("ACCESS_DENIED", json.loads(p.stdout)["error"])

    def test_query_baseline_is_the_search_cards_session_trend(self):
        out = ok(*CONTRACT_ARGS)
        self.assertEqual(out["movers"]["queries"]["baseline_sessions_change_pct"], 6.0)
        self.assertNotIn("warnings", out)

    def test_query_baseline_falls_back_to_search_visits_with_a_warning(self):
        out = ok("--qoq", f"search={C / 'yoy_search.json'}", "--queries", C / "queries.json")
        self.assertEqual(out["movers"]["queries"]["baseline_sessions_change_pct"], -3.23)
        self.assertIn("no browse_sessions trend", out["warnings"][0])

    def test_rules_file_is_complete(self):
        rules = json.loads((SCRIPT.parent.parent / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules["notes"]), set(rules) - {"about", "notes"})


if __name__ == "__main__":
    unittest.main()
