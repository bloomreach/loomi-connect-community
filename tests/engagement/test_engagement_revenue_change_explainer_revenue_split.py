import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/engagement-revenue-change-explainer"
SCRIPT = SKILL / "scripts/revenue_split.py"
FIX = ROOT / "tests/fixtures/engagement/engagement-revenue-change-explainer"


def f(name):
    return str(FIX / name)


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp,
                           capture_output=True, text=True, encoding="utf-8")
    return r.returncode, json.loads(r.stdout) if r.stdout.strip() else r.stderr


def worked(*extra):
    code, out = run("--previous", f("k_previous.json"), "--current", f("k_current.json"), *extra)
    if code:
        raise AssertionError(out)
    return out


class RevenueSplitTest(unittest.TestCase):
    def test_help(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--breakdown", r.stdout)

    def test_rules_every_key_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))

    def test_worked_example_adds_up_exactly(self):
        """The worked example in references/decomposition.md."""
        out = worked()
        self.assertEqual(out["previous"]["revenue"], 280000)  # "280,000.00" parsed, refunded row left out
        self.assertEqual(out["current"]["orders"], 1750)
        self.assertEqual(out["change"], 287000)
        self.assertEqual(out["ratios"]["revenue"], 2.025)
        self.assertTrue(out["ratio_check"]["matches"])
        self.assertEqual(out["main_driver"], "buyers")
        self.assertEqual(out["money_split"], {"buyers": 253344.79, "orders_per_buyer": 30933.21,
                                              "order_value": 2722.0, "unsplit": 0.0})
        self.assertAlmostEqual(sum(v for k, v in out["money_split"].items()), 287000, places=2)
        self.assertTrue(out["money_split_adds_up"])
        self.assertEqual([x["status"] for x in out["previous"]["left_out"]], ["refunded", "null"])

    def test_worked_example_numbers_are_in_the_doc(self):
        doc = (SKILL / "references/decomposition.md").read_text(encoding="utf-8")
        for text in ("+253,344.79", "+30,933.21", "+2,722.00", "406,763.50", "287,000.00"):
            self.assertIn(text, doc)

    def test_per_day(self):
        out = worked("--previous-days", "30", "--current-days", "31")
        self.assertEqual(out["per_day"]["previous"], 9333.33)
        self.assertFalse(out["per_day"]["change_is_the_extra_days"])
        code, out = run("--previous", f("k_previous.json"), "--current", f("k_previous.json"),
                        "--previous-days", "60", "--current-days", "61")
        self.assertEqual(code, 0, out)
        self.assertTrue(out["per_day"]["change_is_the_extra_days"])  # one more day, per day within per_day_tolerance

    def test_buyer_groups_cross_check(self):
        g = worked("--buyer-groups", f"{f('r_previous.json')},{f('r_current.json')}")["buyer_groups"]
        self.assertTrue(g["previous"]["matches_buyers"])
        self.assertTrue(g["current"]["matches_buyers"])
        self.assertEqual(g["change"]["reactivated"], 1170)
        self.assertNotIn("warning", g)
        g = worked("--buyer-groups", f"{f('r_current.json')},{f('r_previous.json')}")["buyer_groups"]
        self.assertIn("warning", g)

    def test_breakdown_adds_up_and_na_is_missing_not_zero(self):
        b = worked("--breakdown", f"campaign={f('b_previous.json')},{f('b_current.json')}")["breakdowns"][0]
        self.assertTrue(b["adds_up"])
        self.assertEqual(b["segments"][0]["segment"], "null")
        self.assertEqual(b["segments"][0]["share_of_change"], 0.6969)
        gone = next(s for s in b["segments"] if s["segment"] == "Spring sale")
        self.assertEqual(gone["revenue_change"], -30000)
        out = worked("--breakdown", f"campaign={f('b_previous.json')},{f('b_current_na.json')}")
        b = out["breakdowns"][0]
        na = next(s for s in b["segments"] if s["segment"] == "Newsletter")
        self.assertIsNone(na["revenue_change"])  # NA is missing, not 0 (0 would read as -50,000)
        self.assertFalse(b["adds_up"])
        self.assertIn("warning", b)
        self.assertEqual(len(out["missing_values"]["left_out_of_sums"]), 1)
        self.assertIn("b_current_na.json", out["missing_values"]["left_out_of_sums"][0])

    def test_max_breakdowns(self):
        spec = f"campaign={f('b_previous.json')},{f('b_current.json')}"
        out = worked(*["--breakdown", spec] * 5)
        self.assertEqual(len(out["breakdowns"]), 4)
        self.assertIn("Ask the user", out["breakdowns_skipped"])

    def test_order_ids_counts_never_ids(self):
        out = worked("--order-ids", f("u_order_ids.json"))
        u = out["order_ids"]
        self.assertEqual(u["most_events_per_id"], 3)
        self.assertEqual(u["ids_repeating"], 1)
        self.assertEqual(u["surplus_events"], 2)
        self.assertNotIn("A-100", json.dumps(out))

    def test_status_option(self):
        code, out = run("--previous", f("k_no_completed.json"), "--current", f("k_no_completed.json"))
        self.assertEqual(code, 1)
        self.assertIn("k_no_completed.json", out["error"])
        self.assertIn("pending", out["error"])
        code, out = run("--previous", f("k_no_completed.json"), "--current", f("k_no_completed.json"),
                        "--status", "PENDING")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["change"], 0)

    def test_errors_name_the_file_without_traceback(self):
        cases = [
            (("--previous", f("error.json"), "--current", f("k_current.json")), ["error.json", "Forbidden"]),
            (("--previous", f("k_na_revenue.json"), "--current", f("k_current.json")), ["k_na_revenue.json", "revenue"]),
            (("--previous", f("missing.json"), "--current", f("k_current.json")), ["missing.json", "can't read"]),
            (("--previous", f("k_previous.json"), "--current", f("k_current.json"), "--out",
              str(FIX / "no-such-dir" / "x.json")), ["x.json", "can't write"]),
            (("--previous", f("k_previous.json"), "--current", f("k_current.json"), "--buyer-groups", "one.json"),
             ["--buyer-groups"]),
            (("--previous", f("k_previous.json"), "--current", f("k_current.json"), "--previous-days", "30"),
             ["--current-days"]),
        ]
        for args, needles in cases:
            code, out = run(*args)
            self.assertEqual(code, 1, args)
            self.assertIsInstance(out, dict, out)
            self.assertFalse(out["ok"])
            for n in needles:
                self.assertIn(n, out["error"])

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(SCRIPT), "--previous", f("k_previous.json"),
                                "--current", f("k_current.json"), "--out", "split.json"],
                               cwd=tmp, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stdout)
            saved = json.loads((Path(tmp) / "split.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["change"], 287000)
        self.assertEqual(json.loads(r.stdout)["main_driver"], "buyers")


if __name__ == "__main__":
    unittest.main()
