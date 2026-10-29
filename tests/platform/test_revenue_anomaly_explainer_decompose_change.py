import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plugins/loomi-platform/skills/revenue-anomaly-explainer/scripts/decompose_change.py"
FIX = ROOT / "tests/fixtures/platform/revenue_anomaly"


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp,
                              capture_output=True, text=True)


def trend(name, *extra):
    p = run("--overall", FIX / "overall.json", "--trend", FIX / name, *extra)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)["trend"]


class DecomposeChangeTest(unittest.TestCase):
    def test_help(self):
        self.assertEqual(run("--help").returncode, 0)

    def test_current_first_day_missing_keeps_weekday_pairing(self):
        t = trend("trend_current_first_missing.json")
        self.assertEqual(t["offset_days"], 7)
        self.assertEqual(t["data_gaps"], [{"date": "20261012", "period": "current", "issue": "missing"}])
        self.assertEqual(t["days"][1], {"date": "20261013", "compare_date": "20261006",
                                        "value": 103.0, "compare_value": 103.0, "gap": 0.0})

    def test_previous_last_day_missing(self):
        t = trend("trend_previous_last_missing.json")
        self.assertEqual(t["offset_days"], 7)
        self.assertEqual(t["data_gaps"], [{"date": "20261011", "period": "previous", "issue": "missing"}])

    def test_30_day_period_first_day_missing(self):
        t = trend("trend_30_current_first_missing.json")
        self.assertEqual(t["offset_days"], 30)
        self.assertEqual(len(t["data_gaps"]), 1)

    def test_offset_days_argument_wins(self):
        self.assertEqual(trend("trend_current_first_missing.json", "--offset-days", "7")["offset_days"], 7)

    def test_na_values_are_reported_not_crashing(self):
        p = run("--overall", FIX / "overall_na.json")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["overall"]["revenue"], 0.0)
        self.assertEqual(len(out["missing_values"]["counted_as_zero"]), 3)

    def test_error_response_stops(self):
        p = run("--overall", FIX / "overall_denied.json")
        self.assertEqual(p.returncode, 1)
        out = json.loads(p.stdout)
        self.assertFalse(out["ok"])
        self.assertIn("Loomi Connect returned an error: [ACCESS_DENIED]", out["error"])
        self.assertIn("don't treat it as 'nothing found'", out["error"])

    def contract(self):
        """Each run in contract/runs.json, run from the contract folder (its paths are relative to it)."""
        c = FIX / "contract"
        out = {}
        for name, args in json.loads((c / "runs.json").read_text())["runs"].items():
            p = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=c, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, f"{name}: {p.stderr}")
            out[name] = json.loads(p.stdout)
        return out

    def test_contract_fixture_matches_the_script(self):
        """contract/expected.json is what apps that port these rules test against, so it must stay the script's output."""
        self.assertEqual(self.contract(), json.loads((FIX / "contract/expected.json").read_text()),
                         "the rules changed: regenerate tests/fixtures/platform/revenue_anomaly/contract/expected.json")

    def test_parts_add_up_to_the_cent(self):
        for name, out in self.contract().items():
            segs = [out["overall"], *out.get("channels", {}).values(), *out.get("devices", {}).get("by_device", {}).values()]
            segs += [i for t in out.get("tables", {}).values() for i in t["falling"] + t["rising"]]
            for s in segs:
                if isinstance(s, dict) and "parts" in s:
                    total = sum(v for v in s["parts"].values() if v is not None)
                    self.assertAlmostEqual(total, s["delta"], places=6, msg=f"{name}: {s.get('name')}")

    def test_rules_file_is_complete(self):
        rules = json.loads((SCRIPT.parent.parent / "references/rules.json").read_text())
        self.assertEqual(set(rules["notes"]), set(rules) - {"about", "notes"})


if __name__ == "__main__":
    unittest.main()
