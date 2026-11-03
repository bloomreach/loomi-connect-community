"""Tests for contact-frequency-audit's frequency_distribution.py: buckets from cumulative customer counts,
fatigue, caps and coverage. The fixtures are synthetic."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/contact-frequency-audit"
SCRIPT = SKILL / "scripts/frequency_distribution.py"
FX = ROOT / "tests/fixtures/engagement/contact-frequency-audit"


def run(*args, cwd=None):
    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=cwd or tmp, timeout=60)
        if cwd is None:
            assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return p.returncode, json.loads(p.stdout) if p.stdout else None


def channel(out, name):
    return next(c for c in out["channels"] if c["channel"] == name)


class FrequencyDistributionTest(unittest.TestCase):
    def test_buckets(self):
        code, out = run("--dir", FX)
        self.assertEqual(code, 0)
        email = channel(out, "email")
        got = [(b["label"], b["customers"], b["optout"], b["engaged"]) for b in email["buckets"]]
        self.assertEqual(got, [("1", 3000, 20, 500), ("2-3", 3000, 15, 700), ("4-7", 2500, 25, 1100),
                               ("8-11", 900, 25, 450), ("12-15", 450, 25, 190), ("16+", 150, 10, 60)])
        self.assertEqual(email["buckets"][3]["per_week"], "2.0-2.75")
        self.assertEqual(email["buckets"][3]["optout_rate_pct"], 2.78)
        self.assertFalse(email["buckets"][5]["judged"])

    def test_fatigue_and_cap(self):
        _, out = run("--dir", FX)
        email = channel(out, "email")
        self.assertEqual(email["reference_bucket"], "1")
        self.assertEqual(email["first_fatigued_bucket"], "8-11")
        self.assertEqual(email["recommended_cap"], {
            "basis": "evidence", "per_window": 7, "per_week": 1.75,
            "why": "customers on 8-11 messages a window show a higher opt-out rate"})
        # 1,500 of a 50,000 base is 3%, under share_high_pct: medium.
        self.assertEqual(email["priority"], "medium")
        self.assertTrue(any("only 120 of the 400" in w for w in email["warnings"]))

    def test_share_of_recipients_without_base_is_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            for f in FX.glob("email_*.json"):
                if f.name != "email_base.json":
                    shutil.copy(f, tmp)
            code, out = run("--dir", tmp)
        email = channel(out, "email")
        self.assertEqual(email["priority"], "high")
        self.assertIn("15.0% of recipients", email["findings"][0]["message"])

    def test_chosen_cap_uses_nearest_measured_threshold(self):
        _, out = run("--dir", FX, "--cap", "email=3")
        cap = channel(out, "email")["chosen_cap"]
        self.assertEqual((cap["over_threshold"], cap["customers_over"], cap["share_pct"], cap["of"]),
                         (16, 150, 0.3, "base"))
        self.assertIn("13+", cap["note"])
        _, out = run("--dir", FX, "--cap", "email=2.75")  # 2.75 a week is 11 in 28 days: over it is 12+, measured
        cap = channel(out, "email")["chosen_cap"]
        self.assertEqual((cap["over_threshold"], cap["customers_over"], cap["note"]), (12, 600, None))

    def test_no_fatigue_uses_rule_of_thumb(self):
        _, out = run("--dir", FX)
        sms = channel(out, "sms")
        self.assertEqual(sms["recommended_cap"]["basis"], "rule_of_thumb")
        self.assertEqual(sms["recommended_cap"]["per_week"], 1)
        self.assertEqual(sms["priority"], "low")
        self.assertIn("no engaged counts: fatigue was judged on opt-outs only.", sms["warnings"])

    def test_empty_channel(self):
        _, out = run("--dir", FX)
        push = channel(out, "push")
        self.assertEqual(push["recipients"], 0)
        self.assertEqual(push["findings"][0]["kind"], "no_data")

    def test_explicit_counts_match_dir(self):
        args = [a for k in (1, 2, 4) for a in ("--count", f"sms:all:{k}={FX / f'sms_all_{k}.json'}",
                                               "--count", f"sms:optout:{k}={FX / f'sms_optout_{k}.json'}")]
        _, out = run(*args)
        _, from_dir = run("--dir", FX)
        self.assertEqual(out["channels"][0], channel(from_dir, "sms"))

    def test_errors_stop(self):
        for args in (["--count", f"email:all:1={FX / 'error.json'}"], ["--count", f"email:all:1={FX / 'nope.json'}"],
                     ["--count", f"email:all:1={FX / 'email_all_1.json'}", "--count",
                      f"email:all:1={FX / 'email_all_2.json'}"],
                     ["--count", f"email:all:1={FX / 'email_all_1.json'}", "--cap", "sms=2"], []):
            code, out = run(*args)
            self.assertEqual(code, 1, args)
            self.assertFalse(out["ok"])

    def test_deterministic(self):
        self.assertEqual(run("--dir", FX, "--cap", "email=3"), run("--dir", FX, "--cap", "email=3"))

    def test_out_writes_to_the_working_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run("--dir", FX, "--out", "freq.json", cwd=tmp)
            self.assertEqual(code, 0)
            self.assertEqual(out["channels"], {"email": "medium", "push": "low", "sms": "low"})
            self.assertTrue(json.loads((Path(tmp) / "freq.json").read_text(encoding="utf-8"))["ok"])

    def test_rules_file_is_complete(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules["notes"]), set(rules) - {"about", "notes"})
        self.assertEqual(set(rules["thresholds"]), set(rules["default_caps_per_week"]))


if __name__ == "__main__":
    unittest.main()
