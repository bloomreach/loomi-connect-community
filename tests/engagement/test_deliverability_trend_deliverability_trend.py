"""Tests for deliverability-trend's deliverability_trend.py: weekly rates, guard-rails, drift, spikes and
breakdowns from saved EQL results. The fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/deliverability-trend"
SCRIPT = SKILL / "scripts/deliverability_trend.py"
FX = ROOT / "tests/fixtures/engagement/deliverability-trend"
WINDOW = ["--start", "2026-08-05", "--end", "2026-11-03"]


def run(*args, cwd=None):
    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=cwd or tmp, timeout=60)
        if cwd is None:
            assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return p.returncode, json.loads(p.stdout) if p.stdout else None


def full():
    return run("--daily", FX / "daily.json", "--breakdown", f"sender={FX / 'sender.json'}",
               "--breakdown", f"campaign={FX / 'campaign.json'}", "--scenarios", FX / "scenarios.json",
               "--breakdown", f"new_audience={FX / 'new_audience.json'}",
               "--breakdown", f"spike:2026-09-14={FX / 'spike_week.json'}", *WINDOW)


class DeliverabilityTrendTest(unittest.TestCase):
    def test_weeks_and_rates(self):
        code, out = run("--daily", FX / "daily.json", *WINDOW)
        self.assertEqual(code, 0)
        self.assertEqual(out["sends_basis"], "enqueued")
        weeks = out["weeks"]
        self.assertEqual(len(weeks), 14)
        # Local-midnight timestamps (UTC+1, then UTC after the clock change) land on the right Monday weeks.
        self.assertEqual(weeks[0]["week"], "2026-08-03")
        self.assertTrue(weeks[0]["partial"])
        self.assertEqual(weeks[0]["sends"], 5000)
        self.assertEqual([w["week"] for w in weeks if w["recent"]], ["2026-10-12", "2026-10-19", "2026-10-26",
                                                                     "2026-11-02"])
        self.assertEqual(out["low_volume_weeks"], ["2026-11-02"])
        self.assertEqual(weeks[-2]["rates_pct"]["complaint_rate"], 0.405)  # 28 / 6909 delivered
        self.assertEqual(out["recent"]["weeks"], 3)
        self.assertEqual(out["baseline"]["weeks"], 10)

    def test_far_east_offsets_keep_monday_in_its_week(self):
        # Local midnight at UTC+13 and UTC+14 is 11:00 or 10:00 UTC the day before.
        for name, offset in (("daily_utc13.json", "13"), ("daily_utc14.json", "14")):
            for extra in (["--start", "2026-11-02"], ["--utc-offset", offset]):
                code, out = run("--daily", FX / name, *extra, "--min-weekly-sends", "1")
                self.assertEqual(code, 0, (name, extra))
                self.assertEqual([(w["week"], w["sends"]) for w in out["weeks"]],
                                 [("2026-11-02", 7000), ("2026-11-09", 14000)], (name, extra))

    def test_timestamp_headers_need_start_or_offset(self):
        code, out = run("--daily", FX / "daily.json")
        self.assertEqual(code, 1)
        self.assertIn("--start", out["error"])

    def test_findings(self):
        _, out = run("--daily", FX / "daily.json", *WINDOW)
        got = [(f["priority"], f["kind"], f["metric"], f["weeks"]) for f in out["findings"]]
        self.assertEqual(got, [
            ("high", "guardrail", "complaint_rate", ["2026-10-26"]),
            ("medium", "drift", "complaint_rate", []),
            ("medium", "spike", "complaint_rate", ["2026-10-26"]),
            ("low", "spike", "hard_bounce_rate", ["2026-09-14"]),
        ])
        self.assertEqual(out["counts"], {"high": 1, "medium": 2, "low": 1})

    def test_exact_threshold_counts_as_crossed(self):
        # cmp-1: 19000 delivered of 20000 sends is exactly 95%, not below the 95% limit, so delivery is 'warn'.
        _, out = full()
        cmp1 = next(r for r in out["breakdowns"]["campaign"]["rows"] if r["name"] == "cmp-1")
        self.assertEqual(cmp1["rates_pct"]["delivery_rate"], 95.0)
        self.assertEqual(cmp1["flags"]["delivery_rate"], "warn")
        self.assertEqual(cmp1["flags"]["hard_bounce_rate"], "limit")

    def test_breakdowns(self):
        code, out = full()
        self.assertEqual(code, 0)
        b = out["breakdowns"]
        self.assertEqual([r["name"] for r in b["sender"]["rows"]], ["shop.example", "mail.example", "(not recorded)"])
        self.assertNotIn("@", json.dumps(b["sender"]))
        self.assertFalse(b["sender"]["rows"][2]["judged"])
        types = {r["name"]: r for r in b["campaign"]["by_type"]}
        self.assertEqual(types["scenario"]["sends"], 58000)
        self.assertEqual(types["one-off campaign"]["sends"], 20300)
        self.assertEqual(b["campaign"]["rows"][0]["name"], "cmp-1")
        new, est = b["new_audience"]["rows"]
        self.assertEqual(new["sends"], 9000)
        self.assertEqual(est["sends"], out["totals"]["sends"] - 9000)
        spike = b["spike:2026-09-14"]["rows"]
        self.assertEqual(spike[0]["name"], "Autumn sale")
        self.assertEqual(spike[0]["share_of_week_problems_pct"], 63.953)  # 110 of 172

    def test_without_scenarios_notes_it(self):
        _, out = run("--daily", FX / "daily.json", "--breakdown", f"campaign={FX / 'campaign.json'}", *WINDOW)
        self.assertNotIn("by_type", out["breakdowns"]["campaign"])
        self.assertIn("--scenarios", out["breakdowns"]["campaign"]["note"])

    def test_sender_not_recorded(self):
        _, out = run("--daily", FX / "daily.json", "--breakdown", f"sender={FX / 'sender_none.json'}", *WINDOW)
        self.assertIn("no sender", out["breakdowns"]["sender"]["note"])

    def test_errors_stop(self):
        for args in (["--daily", FX / "error.json"], ["--daily", FX / "empty.json"],
                     ["--daily", FX / "daily.json", "--breakdown", f"sender={FX / 'error.json'}"],
                     ["--daily", FX / "missing.json"]):
            code, out = run(*args)
            self.assertEqual(code, 1, args)
            self.assertFalse(out["ok"])

    def test_bad_breakdown_name(self):
        p = subprocess.run([sys.executable, str(SCRIPT), "--daily", str(FX / "daily.json"), "--breakdown",
                            f"spike:2026-09-15={FX / 'spike_week.json'}"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)  # not a Monday

    def test_deterministic(self):
        self.assertEqual(full(), full())

    def test_out_writes_to_the_working_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run("--daily", FX / "daily.json", *WINDOW, "--out", "trend.json", cwd=tmp)
            self.assertEqual(code, 0)
            self.assertEqual(out["counts"]["high"], 1)
            self.assertTrue(json.loads((Path(tmp) / "trend.json").read_text(encoding="utf-8"))["ok"])

    def test_rules_file_is_complete(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules["notes"]), set(rules) - {"about", "notes"})
        self.assertTrue(rules["about"])


if __name__ == "__main__":
    unittest.main()
