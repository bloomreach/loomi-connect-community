"""Tests for data-retention-review's data_retention_review.py. The fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-platform/skills/data-retention-review"
SCRIPT = SKILL / "scripts/data_retention_review.py"
FX = ROOT / "tests/fixtures/platform/data_retention_review"


def run(*args):
    """Run the script by its full path from an empty working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def review(*args):
    r = run(*args)
    if r.returncode:
        raise AssertionError(r.stdout + r.stderr)
    return json.loads(r.stdout)


FULL = ("--retention", FX / "retention.json",
        "--definition", f"aggregate={FX / 'aggregates.json'}",
        "--definition", f"segmentation={FX / 'segmentation.json'}",
        "--definition", f"report={FX / 'report.json'}",
        "--definition", f"funnel={FX / 'funnel.json'}",
        "--event-schema", FX / "event_schema.json",
        "--customer-schema", FX / "customer_schema.json", "--today", "2026-11-04")


def found(out):
    return {(f["priority"], f["check"], f["subject"], f["name"]) for f in out["findings"]}


class DataRetentionReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = review(*FULL)
        cls.f = found(cls.out)

    def test_windows_against_retention(self):
        self.assertIn(("high", "window longer than retention", "purchase", "Bought in the last two years"), self.f)
        self.assertIn(("high", "window never satisfiable", "purchase", "Orders older than 13 months"), self.f)
        self.assertIn(("medium", "lifetime window on expiring events", "purchase", "Lifetime orders"), self.f)
        # Reports aren't live, so a too-long window is medium; the member's disabled filter follows the report date.
        self.assertIn(("medium", "window longer than retention", "page_visit", "Quarterly traffic"), self.f)

    def test_window_shapes(self):
        w = {(x["kind"], x["name"], x["event"], x["mode"]): x["window"] for x in self.out["windows"]}
        self.assertEqual(w[("segmentation", "Bought in the last two years", "purchase", "rolling")], "730 days")
        self.assertEqual(w[("report", "Quarterly traffic", "page_visit", "rolling")], "90 days")
        self.assertEqual(w[("funnel", "Browse to buy", "view_item", "absolute")], "126 days")
        self.assertEqual(w[("aggregate", "Orders older than 13 months", "purchase", "older_than")], "395.4 days")
        self.assertFalse(any(x["name"] == "Old archived" for x in self.out["windows"]))
        self.assertIn("1 archived definition(s) skipped.", self.out["not_checked"])

    def test_skill_needs(self):
        self.assertIn(("medium", "skill window longer than retention", "purchase", "winback-opportunity"), self.f)
        self.assertIn(("medium", "skill window longer than retention", "campaign", "deliverability-trend"), self.f)
        self.assertIn(("medium", "skill window longer than retention", "page_visit", "engagement-tracking-health"), self.f)
        # cart_update isn't tracked in this project, so funnel-leak-finder's need for it is skipped.
        self.assertFalse(any(x[2] == "cart_update" for x in self.f))
        out = review(*FULL, "--no-skill-needs")
        self.assertFalse(any(x["check"] == "skill window longer than retention" for x in out["findings"]))

    def test_over_kept(self):
        self.assertIn(("medium", "personal data kept longer than used", "newsletter_signup", None), self.f)
        self.assertIn(("low", "kept forever, nothing reads it", "consent", None), self.f)
        self.assertIn(("low", "kept forever, read briefly", "view_item", None), self.f)
        self.assertIn(("low", "kept much longer than read", "session_start", None), self.f)
        self.assertIn(("low", "rule for an unknown event", "old_event", None), self.f)
        row = next(r for r in self.out["events"] if r["event"] == "campaign")
        self.assertEqual(row["retention"], "1 day")

    def test_personal_properties_names_only(self):
        self.assertIn(("high", "personal customer property without retention", "birth_date, wifeBirthdate", None), self.f)
        self.assertIn(("medium", "personal customer property without retention", "email, first_name", None), self.f)
        self.assertIn(("low", "personal customer property without retention", "city", None), self.f)
        self.assertIn(("low", "personal property never filled", "birth_date", None), self.f)
        text = json.dumps(self.out)
        for name in ("_tax_exempt", "favourite_product_name", "Loyalty points"):
            self.assertNotIn(name, text)
        self.assertNotIn("FAKE-person", run(*FULL).stdout)

    def test_default_retention(self):
        out = review("--retention", FX / "retention_default.json", "--definition", f"report={FX / 'report.json'}",
                     "--event-schema", FX / "event_schema.json", "--today", "2026-11-04")
        self.assertEqual(out["default_retention"], "182.5 days")
        # The 90-day report fits in six months; purchase is kept for ever (its override is off) and carries an
        # email property, while the longest read is win-back's 730 days.
        self.assertEqual([(x["priority"], x["check"], x["subject"]) for x in out["findings"]],
                         [("medium", "personal data kept longer than used", "purchase")])

    def test_disclaimer_sorting_and_repeatability(self):
        self.assertIn("not legal advice", self.out["disclaimer"])
        order = [("high", "medium", "low").index(x["priority"]) for x in self.out["findings"]]
        self.assertEqual(order, sorted(order))
        self.assertEqual(sum(self.out["counts"].values()), len(self.out["findings"]))
        self.assertEqual(review(*FULL), self.out)

    def test_errors(self):
        r = run("--retention", FX / "access_error.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("project or access", json.loads(r.stdout)["error"])
        r = run("--retention", FX / "retention.json", "--definition", f"widget={FX / 'report.json'}")
        self.assertNotEqual(r.returncode, 0)
        r = run("--retention", FX / "missing.json")
        self.assertEqual(r.returncode, 1)

    def test_denied_kind_is_not_checked_but_401_stops(self):
        out = review(*FULL, "--definition", f"prediction={FX / 'predictions_denied.json'}")
        self.assertTrue(any(n.startswith("prediction (") and "ACCESS_DENIED" in n for n in out["not_checked"]))
        self.assertEqual(out["findings"], self.out["findings"])
        r = run(*FULL, "--definition", f"prediction={FX / 'unauthorized.json'}")
        self.assertEqual(r.returncode, 1)
        self.assertIn("project or access", json.loads(r.stdout)["error"])

    def test_unreadable_timestamp_conditions(self):
        out = review("--retention", FX / "retention.json", "--definition",
                     f"aggregate={FX / 'aggregates_odd_timestamps.json'}", "--no-skill-needs", "--today", "2026-11-04")
        notes = [n for n in out["not_checked"] if "timestamp condition couldn't be read" in n]
        # not_checked is de-duplicated: one line per definition with an unreadable condition.
        self.assertEqual(notes, ["aggregate 'Between dates': a timestamp condition couldn't be read.",
                                 "aggregate 'Odd units': a timestamp condition couldn't be read."])
        self.assertFalse(any(w["mode"] in ("in_last", "older_than") for w in out["windows"]))

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "review.json"
            r = subprocess.run([sys.executable, str(SCRIPT), *map(str, FULL), "--out", str(target)],
                               capture_output=True, text=True, encoding="utf-8", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), json.loads(r.stdout))
            r = subprocess.run([sys.executable, str(SCRIPT), *map(str, FULL), "--out", str(Path(tmp) / "no/dir.json")],
                               capture_output=True, text=True, encoding="utf-8", cwd=tmp)
            self.assertEqual(r.returncode, 1)

    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        keys = set(rules) - {"about", "notes"}
        self.assertEqual(keys, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
