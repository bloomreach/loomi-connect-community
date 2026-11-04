import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/engagement-journey-health"
SCRIPT = SKILL / "scripts/journey_flags.py"
FX = ROOT / "tests/fixtures/engagement/engagement-journey-health"


def run(*args, cwd=None):
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              cwd=cwd or tmp, capture_output=True, text=True, encoding="utf-8")


class JourneyFlagsTest(unittest.TestCase):
    def test_help(self):
        self.assertEqual(run("--help").returncode, 0)

    def test_flags_and_ranking(self):
        r = run(FX / "current.json", "--previous", FX / "previous.json", "--scenarios", FX / "scenarios.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = [l for l in r.stdout.splitlines() if l.startswith("| high") or l.startswith("| medium")]
        # High first, the bigger loss first within a severity.
        self.assertTrue(lines[0].startswith("| high | Welcome series | 2 | 1,000 | 200 | 80.0% | 900 |"), lines)
        self.assertIn("80% not delivered (mostly suppressed)", lines[0])
        self.assertIn("not-delivered share rose 10 → 80%", lines[0])
        self.assertTrue(lines[1].startswith("| high | Birthday offer | 5 |"), lines)
        self.assertIn("delivered 400 → 0 (-100%)", lines[1])
        # hard_bounced (the live spelling) counts as a bounce.
        self.assertTrue(lines[2].startswith("| medium | Welcome series | 8 | 1,000 | 600 | 40.0% |"), lines)
        self.assertIn("40% not delivered (mostly hard_bounced)", lines[2])
        self.assertTrue(lines[3].startswith("| medium | Welcome series | 1 | 950 | 900 | 5.3% |"), lines)
        self.assertIn("5.3% errors", lines[3])
        self.assertIn("delivered 2,000 → 900 (-55%)", lines[3])
        self.assertEqual(len(lines), 4)
        self.assertIn("Active scenarios with no campaign events in the period: Birthday offer", r.stdout)
        self.assertNotIn("Old draft", r.stdout)
        self.assertIn("not in the scenario list (a standalone campaign or an inactive scenario): dddddddddddddddddddddddd", r.stdout)
        self.assertIn("Statuses not in rules.json, not counted: dropped", r.stdout)
        self.assertIn("Rows with only zeros dropped: 1", r.stdout)

    def test_json_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "flags.json"
            r = run(FX / "current.json", "--previous", FX / "previous.json", "--out", out, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(out.read_text(encoding="utf-8"))
        steps = {(s["campaign_id"][:1], s["action_id"]): s for s in data["steps"]}
        # Bounces count as sent but not delivered: reached 950, lost 50.
        self.assertEqual(steps[("a", 1)]["current"]["reached"], 950)
        self.assertEqual(steps[("a", 1)]["current"]["lost"], 50)
        # Enqueued with no receipts: delivery unknown, nothing lost, no flag.
        self.assertTrue(steps[("b", 3)]["current"]["unknown_delivery"])
        self.assertEqual(steps[("b", 3)]["current"]["lost"], 0)
        self.assertIsNone(steps[("b", 3)]["severity"])
        # SMS records sent and no delivered: delivery unknown, not lost, no flag.
        sms = steps[("b", 6)]["current"]
        self.assertEqual((sms["reached"], sms["lost"]), (400, 0))
        self.assertTrue(sms["unknown_delivery"])
        self.assertIsNone(steps[("b", 6)]["severity"])
        # Email with hard_bounced and soft_bounced: both are bounces, not unknown statuses.
        email = steps[("a", 8)]["current"]
        self.assertEqual((email["reached"], email["lost"], email["errors"]), (1000, 400, 400))
        self.assertEqual(email["unknown_statuses"], [])
        # Under min_reached: listed, never flagged.
        self.assertEqual(steps[("b", 4)]["current"]["reached"], 60)
        self.assertIsNone(steps[("b", 4)]["severity"])
        # Without --scenarios there's no silent list.
        self.assertEqual(data["silent_active_scenarios"], [])

    def test_error_response(self):
        r = run(ROOT / "tests/fixtures/engagement/denied.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Loomi Connect returned an error: [ACCESS_DENIED]", r.stderr)
        self.assertIn("denied.json", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_names_are_escaped_in_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            scen = Path(tmp) / "scenarios.json"
            scen.write_text(json.dumps({"data": [
                {"_id": "aaaaaaaaaaaaaaaaaaaaaaaa", "name": "Bad | name ![x](http://e.test) <img> `code`", "status": "active"},
                {"_id": "cccccccccccccccccccccccc", "name": "Quiet|flow", "status": "active"}]}), encoding="utf-8")
            r = run(FX / "current.json", "--previous", FX / "previous.json", "--scenarios", scen, cwd=tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("| high | Bad \\| name !\\[x](http://e.test) &lt;img> \\`code\\` | 2 |", r.stdout)
        self.assertNotIn("<img>", r.stdout)
        self.assertNotIn("![", r.stdout)
        self.assertIn("Quiet\\|flow", r.stdout)
        # Every table row still has the same number of unescaped cell separators.
        for line in r.stdout.splitlines():
            if line.startswith("| high") or line.startswith("| medium"):
                self.assertEqual(len(re.findall(r"(?<!\\)\|", line)), 9, line)

    def test_unparseable_cells_are_missing_not_zero(self):
        doc = json.loads((FX / "current.json").read_text(encoding="utf-8"))
        doc["data"]["rows"][0]["values"][0] = "NA"
        with tempfile.TemporaryDirectory() as tmp:
            cur = Path(tmp) / "current.json"
            cur.write_text(json.dumps(doc), encoding="utf-8")
            out = Path(tmp) / "flags.json"
            r = run(cur, "--out", out, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("Cells that weren't numbers, treated as missing: 1", r.stdout)
        self.assertEqual(data["missing_cells"], 1)

    def test_bad_input_names_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "broken.json"
            bad.write_text("{not json", encoding="utf-8")
            notcrosstab = Path(tmp) / "list.json"
            notcrosstab.write_text(json.dumps({"success": True, "data": [1, 2]}), encoding="utf-8")
            cases = [(bad, "not valid JSON"), (Path(tmp) / "missing.json", "can't read the file"),
                     (notcrosstab, "no EQL rows found")]
            for path, text in cases:
                r = run(path, cwd=tmp)
                self.assertEqual(r.returncode, 1, path)
                self.assertIn(str(path), r.stderr)
                self.assertIn(text, r.stderr)
                self.assertNotIn("Traceback", r.stderr)
            r = run(FX / "current.json", "--scenarios", bad, cwd=tmp)
            self.assertEqual(r.returncode, 1)
            self.assertIn("broken.json", r.stderr)
            self.assertNotIn("Traceback", r.stderr)

    def test_out_that_cannot_be_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "no-such-folder" / "flags.json"
            r = run(FX / "current.json", "--out", out, cwd=tmp)
        self.assertEqual(r.returncode, 1)
        self.assertIn(str(out), r.stderr)
        self.assertIn("can't write the file", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules["notes"]), set(rules) - {"about", "notes"})


if __name__ == "__main__":
    unittest.main()
