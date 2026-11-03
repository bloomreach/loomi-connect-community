import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/contactability-audit"
SCRIPT = SKILL / "scripts/contactability_report.py"
FIX = ROOT / "tests/fixtures/engagement/contactability-audit"


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=tmp, capture_output=True, text=True, encoding="utf-8")
    return r.returncode, json.loads(r.stdout) if r.stdout.strip() else r.stderr


def full(*extra):
    f = lambda n: str(FIX / n)
    code, out = run("--base", f("base.json"), "--has-id", f"email={f('email_id.json')}", "--reachable", f"email={f('email_reachable.json')}",
                    "--has-id", "sms=4,000", "--reachable", "sms=3500", "--has-id", "push=1500", "--any-reachable", "4000",
                    "--high-value", f("hv.json"), "--high-value-unreachable", f("hv_unreachable.json"),
                    "--consent-trend", f("consent_trend.json"), "--consent-categories", f("consent_settings.json"),
                    "--consent-by-category", f("consent_by_category.json"), "--holders", "partner_offers=0", *extra)
    if code:
        raise AssertionError(out)
    return out


def kinds(out):
    return {(x["kind"], x.get("channel") or x.get("category") or x.get("month")): x["priority"] for x in out["findings"]}


class ContactabilityReportTest(unittest.TestCase):
    def test_rules_every_key_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))

    def test_channel_shares_and_consent_gap(self):
        out = full()
        email, sms, push = out["channels"]
        self.assertEqual([c["channel"] for c in out["channels"]], ["email", "sms", "push"])
        self.assertEqual(out["base"], 10000)  # both EQL rows added up
        self.assertEqual(email["reachable_share"], 0.25)
        self.assertEqual(email["consent_gap_share"], 0.55)
        self.assertEqual(sms["has_identifier"], 4000)  # "4,000" parsed
        self.assertIsNone(push["reachable_share"])
        k = kinds(out)
        self.assertEqual(k[("low_reach", "email")], "high")  # primary channel
        self.assertEqual(k[("limited_reach", "sms")], "low")  # not primary
        self.assertEqual(k[("consent_gap", "email")], "medium")
        self.assertNotIn(("consent_gap", "sms"), k)
        self.assertEqual(k[("not_measured", "push")], "low")
        self.assertEqual(k[("unreachable", None)], "medium")

    def test_high_value_unreachable(self):
        out = full()
        self.assertEqual(out["high_value"]["unreachable_share"], 0.35)
        self.assertEqual(kinds(out)[("high_value_unreachable", None)], "high")

    def test_consent_trend_months_shrinking_and_spike(self):
        out = full()
        trend = out["consent_trend"]
        # local month starts (an hour before UTC midnight) land in the right month
        self.assertEqual([t["month"] for t in trend], ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"])
        self.assertEqual(trend[-1]["net"], -30)
        self.assertEqual(trend[0]["other"], 1)  # the null action column is neither in nor out
        k = kinds(out)
        self.assertEqual(k[("list_shrinking", None)], "high")
        self.assertEqual(k[("optout_spike", "2026-07")], "medium")
        self.assertNotIn(("optout_spike", "2026-09"), k)

    def test_thin_trend_is_not_read(self):
        code, out = run("--base", "100", "--consent-trend", str(FIX / "consent_trend_thin.json"))
        self.assertEqual(code, 0)
        k = kinds(out)
        self.assertIn(("trend_thin", None), k)
        self.assertNotIn(("list_shrinking", None), k)

    def test_categories(self):
        out = full()
        use = {c["id"]: c["use"] for c in out["categories"]}
        self.assertEqual(use, {"existing_clients": "legitimate interest", "newsletter": "in use", "old_survey": "no events in window",
                               "partner_offers": "unused", "sms": "in use"})
        k = kinds(out)
        self.assertEqual(k[("category_unused", "partner_offers")], "medium")
        self.assertEqual(k[("category_quiet", "old_survey")], "low")
        self.assertEqual(k[("category_undefined", "promo_legacy")], "low")
        self.assertNotIn(("category_quiet", "existing_clients"), k)
        self.assertIn("notification", out["categories_note"])

    def test_findings_sorted_and_deterministic(self):
        a, b = full(), full()
        self.assertEqual(a, b)
        order = {"high": 0, "medium": 1, "low": 2}
        self.assertEqual([order[f["priority"]] for f in a["findings"]], sorted(order[f["priority"]] for f in a["findings"]))

    def test_empty_rows_count_as_zero(self):
        code, out = run("--base", "1000", "--has-id", "email=900", "--reachable", f"email={FIX / 'empty_count.json'}")
        self.assertEqual(code, 0)
        self.assertEqual(out["channels"][0]["reachable"], 0)
        self.assertEqual(kinds(out)[("low_reach", "email")], "high")

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(SCRIPT), "--base", "100", "--out", "report.json"],
                               cwd=tmp, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertTrue(json.loads((Path(tmp) / "report.json").read_text(encoding="utf-8"))["ok"])

    def test_errors(self):
        code, out = run("--base", str(FIX / "error.json"))
        self.assertEqual(code, 1)
        self.assertIn("Forbidden", out["error"])
        code, out = run("--base", "0")
        self.assertEqual(code, 1)
        code, out = run("--base", "lots")
        self.assertEqual(code, 1)
        code, out = run("--base", "100", "--high-value", "10")
        self.assertEqual(code, 1)
        code, out = run("--base", "100", "--consent-categories", str(FIX / "base.json"))
        self.assertEqual(code, 1)
        code, out = run("--base", "100", "--consent-trend", str(FIX / "missing.json"))
        self.assertEqual(code, 1)
        self.assertIn("can't read", out["error"])
        code, out = run("--base", "100", "--out", str(FIX / "no-such-dir" / "x.json"))
        self.assertEqual(code, 1)
        self.assertIn("can't write", out["error"])


if __name__ == "__main__":
    unittest.main()
