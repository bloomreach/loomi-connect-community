"""Tests for engagement-send-preflight's preflight_report.py: joining the campaign calendar with
message_checks.py findings. The fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "plugins/loomi-engagement/skills/engagement-send-preflight/scripts"
FX = ROOT / "tests/fixtures/engagement/message_checks"


def run(script, *args):
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r.returncode, json.loads(r.stdout) if r.stdout else None


class PreflightReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.findings = Path(cls.tmp.name) / "findings.json"
        code, _ = run("message_checks.py", FX / "scenario.json", FX / "email_broken.json", FX / "sms_campaign.json",
                      "--out", cls.findings)
        assert code == 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def report(self, *extra):
        return run("preflight_report.py", "--calendar", FX / "preflight_calendar.json", "--findings", self.findings,
                   "--from", "2026-11-04T00:00:00Z", "--to", "2026-11-11T00:00:00Z", *extra)

    def test_rows_and_verdicts(self):
        code, out = self.report()
        self.assertEqual(code, 0)
        got = [(r["campaign"], r["step"], r["verdict"]) for r in out["sends"]]
        self.assertEqual(got, [
            ("Broken promo", "Broken promo", "NO-GO"),
            ("Cart flow", "Cart email", "GO"),
            ("Cart flow", "Cart SMS", "GO"),
            ("Cart flow", "Cart push", "NO-GO"),
            ("Cart flow", "Cart WhatsApp", "NOT CHECKED"),
            ("Weekend SMS", "Weekend SMS", "NO-GO"),
            ("Not fetched yet", "Email", "NOT CHECKED"),
        ])
        self.assertEqual(out["overall"], "NO-GO")
        self.assertEqual(out["totals"], {"NO-GO": 3, "GO WITH CAUTION": 0, "GO": 2, "NOT CHECKED": 2})
        self.assertEqual(out["left_out"], {"webhook steps": 1, "draft sends": 1})

    def test_counts_cover_every_variant(self):
        _, out = self.report()
        promo = next(r for r in out["sends"] if r["campaign"] == "Broken promo")
        self.assertEqual(promo["messages"], 2)
        self.assertEqual(promo["top_findings"][0]["severity"], "blocker")
        self.assertLessEqual(len(promo["top_findings"]), 5)
        cart = next(r for r in out["sends"] if r["step"] == "Cart email")
        self.assertEqual(cart["sends_in_window"], 2)
        self.assertEqual(cart["first_send"], "2026-11-04T09:00Z")

    def test_not_checked_reasons(self):
        _, out = self.report()
        reasons = {r["step"] if r["campaign"] == "Cart flow" else r["campaign"]: r["not_checked_reason"]
                   for r in out["sends"] if r["verdict"] == "NOT CHECKED"}
        self.assertIn("whatsapp isn't covered", reasons["Cart WhatsApp"])
        self.assertIn("run message_checks.py", reasons["Not fetched yet"])

    def test_include_drafts_and_webhooks(self):
        _, out = self.report("--include-drafts", "--include-webhooks")
        names = {(r["campaign"], r["step"]) for r in out["sends"]}
        self.assertIn(("Old draft", "Email"), names)
        self.assertIn(("Cart flow", "Notify CRM"), names)
        self.assertEqual(out["left_out"], {})

    def test_window(self):
        _, out = run("preflight_report.py", "--calendar", FX / "preflight_calendar.json", "--findings", self.findings)
        self.assertIn("Next month", {r["campaign"] for r in out["sends"]})

    def test_nothing_scheduled(self):
        _, out = run("preflight_report.py", "--calendar", FX / "preflight_calendar.json", "--findings", self.findings,
                     "--from", "2030-01-01T00:00:00Z")
        self.assertEqual(out["overall"], "NOTHING SCHEDULED")

    def test_errors(self):
        code, out = run("preflight_report.py", "--calendar", FX / "error.json", "--findings", self.findings)
        self.assertEqual(code, 1)
        self.assertIn("ACCESS_DENIED", out["error"])
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"ok": False, "error": "design stripped"}), encoding="utf-8")
            code, out = run("preflight_report.py", "--calendar", FX / "preflight_calendar.json", "--findings", bad)
            self.assertEqual(code, 1)
            self.assertIn("message checks failed", out["error"])


    def test_bad_date(self):
        code, _ = run("preflight_report.py", "--calendar", FX / "preflight_calendar.json", "--findings", self.findings,
                      "--from", "notadate")
        self.assertEqual(code, 2)


class SendWindowTest(unittest.TestCase):
    def test_weeks(self):
        _, out = run("send_window.py", "--now", "2026-11-03T09:00:00Z", "--days", "10")
        self.assertEqual((out["from"], out["to"]), ("2026-11-03T09:00:00Z", "2026-11-13T09:00:00Z"))
        self.assertEqual([(c["from"], c["to"]) for c in out["calendar_calls"]],
                         [("2026-11-03T09:00:00Z", "2026-11-10T09:00:00Z"), ("2026-11-10T09:00:00Z", "2026-11-13T09:00:00Z")])
        self.assertEqual(out["calendar_calls"][0]["from_ts"], 1793696400)

    def test_default_days_from_rules(self):
        rules = json.loads((SCRIPTS.parent / "references/preflight-rules.json").read_text(encoding="utf-8"))
        _, out = run("send_window.py", "--now", "2026-11-03T00:00:00Z")
        self.assertEqual(len(out["calendar_calls"]), -(-rules["window_days"] // 7))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))

    def test_recently_edited_live_flows(self):
        # 2026-11-03T09:00Z is 1793696400; Welcome was edited 2.3 days before, Cart 19.7 days before.
        _, out = run("send_window.py", "--now", "2026-11-03T09:00:00Z", "--scenarios", FX / "scenarios_list.json")
        self.assertEqual([s["name"] for s in out["recently_edited"]], ["Welcome flow"])
        self.assertEqual(out["not_recent"], ["Cart flow"])

    def test_bad_input(self):
        code, out = run("send_window.py", "--days", "0")
        self.assertEqual(code, 1)
        code, out = run("send_window.py", "--scenarios", FX / "error.json")
        self.assertEqual(code, 1)
        self.assertIn("ACCESS_DENIED", out["error"])


if __name__ == "__main__":
    unittest.main()
