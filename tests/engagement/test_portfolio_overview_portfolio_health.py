"""Tests for portfolio-overview's portfolio_health.py. The fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/portfolio-overview"
SCRIPT = SKILL / "scripts/portfolio_health.py"
FIX = ROOT / "tests/fixtures/engagement/portfolio-overview"


def run(*args):
    """Run the script by its full path from a fresh working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp, capture_output=True,
                           text=True, encoding="utf-8", timeout=60)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def full():
    r = run("--overview", FIX / "overview.json", "--overview", FIX / "overview_other_org.json",
            "--recent", f"Brand Bravo={FIX / 'recent_bravo_empty.json'}",
            "--recent", f"p-alpha-0001={FIX / 'recent_alpha_partial.json'}",
            "--recent", f"brand charlie={FIX / 'recent_charlie_ok.json'}",
            "--scenarios", f"Brand Bravo={FIX / 'scenarios_bravo_none.json'}",
            "--scenarios", f"Brand Charlie={FIX / 'scenarios_charlie_two.json'}",
            "--baseline", FIX / "baseline.json", "--today", "2026-11-04")
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout), r.stdout


def project(out, name):
    return next(p for p in out["projects"] if p["name"] == name)


def codes(p):
    return [f["code"] for f in p["flags"]]


class PortfolioHealthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out, cls.raw = full()

    def test_projects_deduplicated_across_orgs(self):
        self.assertEqual(self.out["portfolio"]["projects"], 10)
        self.assertEqual(self.out["portfolio"]["comparable_projects"], 7)

    def test_deeper_mode_flags(self):
        bravo = project(self.out, "Brand Bravo")
        self.assertEqual(sorted(codes(bravo)), ["no_live_scenarios", "no_recent_events"])
        self.assertEqual((bravo["score"], bravo["band"], bravo["live_scenarios"]), (35, "red", 0))
        alpha = project(self.out, "Brand Alpha")
        self.assertEqual(codes(alpha), ["busy_types_silent"])
        self.assertIn("page_visit, view_item", alpha["flags"][0]["detail"])
        charlie = project(self.out, "Brand Charlie")
        self.assertEqual(charlie["live_scenarios"], 2)
        self.assertEqual(charlie["recent_events_7d"], 9010)

    def test_overview_only_flags(self):
        self.assertEqual(codes(project(self.out, "Brand Echo")), ["no_events"])
        self.assertEqual(sorted(codes(project(self.out, "Brand Delta"))), ["outlier_low", "small_customer_base"])
        self.assertEqual(codes(project(self.out, "Brand Hotel")), ["no_campaign_events"])
        self.assertEqual(codes(project(self.out, "Brand India")), ["outlier_high"])
        self.assertEqual(codes(project(self.out, "Fox Test Sandbox")), ["test_or_sandbox"])

    def test_test_words_match_whole_words_only(self):
        self.assertEqual(codes(project(self.out, "Contest Hub")), [])
        self.assertIsNone(project(self.out, "Contest Hub")["test_like"])

    def test_baseline_shrink(self):
        charlie = project(self.out, "Brand Charlie")
        self.assertEqual(sorted(codes(charlie)), ["fewer_events", "shrinking_customers"])
        self.assertIn("since 2026-08-01", charlie["flags"][0]["detail"])
        self.assertNotIn("shrinking_customers", codes(project(self.out, "Brand Alpha")))

    def test_overview_error_unscored_and_redacted(self):
        golf = project(self.out, "Brand Golf")
        self.assertEqual((golf["score"], golf["band"]), (None, "unknown"))
        self.assertNotIn("api.example.test", self.raw)
        self.assertNotIn("FAKE", self.raw)
        self.assertEqual(self.out["projects"][0]["name"], "Brand Golf")

    def test_sorted_by_score_and_handoffs(self):
        scores = [p["score"] for p in self.out["projects"] if p["score"] is not None]
        self.assertEqual(scores, sorted(scores))
        skills = {h["skill"]: [p["name"] for p in h["projects"]] for h in self.out["handoffs"]}
        self.assertIn("Brand Bravo", skills["lifecycle-coverage-map"])
        self.assertIn("Brand Echo", skills["engagement-tracking-health"])
        self.assertNotIn("Fox Test Sandbox", sum(skills.values(), []))

    def test_deeper_mode_candidates_and_call_count(self):
        deep = self.out["deeper_mode"]
        names = [c["name"] for c in deep["candidates"]]
        self.assertEqual(names[0], "Brand Delta")
        self.assertEqual(names[-1], "Fox Test Sandbox")
        self.assertNotIn("Brand Echo", names)
        self.assertNotIn("Brand Bravo", names)
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(deep["calls_needed"], len(names) * rules["deep_calls_per_project"])
        capped = json.loads(run("--overview", FIX / "overview.json", "--max-deep", "2").stdout)
        self.assertEqual(len(capped["deeper_mode"]["candidates"]), 2)
        self.assertEqual(capped["deeper_mode"]["more_not_listed"], 6)

    def test_never_prints_editor_names(self):
        self.assertNotIn("Pat Example", self.raw)

    def test_not_checked_without_deeper_mode(self):
        out = json.loads(run("--overview", FIX / "overview.json").stdout)
        text = " ".join(out["not_checked"])
        self.assertIn("Recent activity", text)
        self.assertIn("Live scenarios", text)
        self.assertIn("baseline", text)

    def test_access_error_stops(self):
        r = run("--overview", FIX / "overview.json", "--scenarios", f"p-alpha-0001={FIX / 'scenarios_denied.json'}")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not checked", json.loads(r.stdout)["error"])

    def test_unknown_project_key_fails(self):
        r = run("--overview", FIX / "overview.json", "--recent", f"Nope={FIX / 'recent_bravo_empty.json'}")
        self.assertEqual(r.returncode, 1)

    def test_table_and_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "portfolio.json"
            r = subprocess.run([sys.executable, str(SCRIPT), "--overview", str(FIX / "overview.json"), "--table",
                                "--out", str(out), "--today", "2026-11-04"], cwd=tmp, capture_output=True,
                               text=True, encoding="utf-8", timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.startswith("| Project |"))
            saved = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(saved["today"], "2026-11-04")

    def test_missing_event_count_is_unknown_not_empty(self):
        out = json.loads(run("--overview", FIX / "overview_events_unknown.json").stdout)
        kilo = out["projects"][0]
        self.assertEqual(codes(kilo), ["events_unknown"])
        self.assertEqual(kilo["score"], 100)
        self.assertEqual(out["deeper_mode"]["candidates"], [])

    def test_handoffs_come_from_rules(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        for p in self.out["projects"]:
            for f in p["flags"]:
                self.assertEqual(f["handoff"], rules["flags"][f["code"]]["handoff"])

    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        missing = [k for k in rules if k not in ("about", "notes") and k not in rules["notes"]]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
