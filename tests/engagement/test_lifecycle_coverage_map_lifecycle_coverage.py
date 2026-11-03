import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/lifecycle-coverage-map"
SCRIPT = SKILL / "scripts/lifecycle_coverage.py"
FIX = ROOT / "tests/fixtures/engagement/lifecycle-coverage-map"
ALL = ",".join(str(FIX / f) for f in ["welcome_live.json", "cart_weak.json", "browse_draft.json", "purchase_replenish.json",
                                      "birthday_stopped.json", "welcome_name_only.json", "postpurchase_disconnected.json"])


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=tmp, capture_output=True, text=True, encoding="utf-8")
    return r.returncode, json.loads(r.stdout) if r.stdout.strip() else r.stderr


def full(*extra):
    code, out = run("--scenario", ALL, "--list", str(FIX / "scenario_list.json"), *extra)
    if code:
        raise AssertionError(out)
    return out, {f["flow"]: f for f in out["flows"]}


class LifecycleCoverageTest(unittest.TestCase):
    def test_rules_every_key_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))
        self.assertEqual(set(rules["flow_order"]), set(rules["flows"]))

    def test_statuses_from_trigger_and_nodes(self):
        out, flows = full()
        self.assertEqual(flows["welcome"]["status"], "live")
        self.assertEqual(flows["browse_abandonment"]["status"], "draft")
        self.assertEqual(flows["cart_abandonment"]["status"], "weak")
        self.assertIn("first message after 48 hours (over 24)", flows["cart_abandonment"]["scenarios"][0]["problems"])
        self.assertEqual(flows["birthday"]["status"], "stopped")
        self.assertEqual(flows["birthday"]["scenarios"][0]["confidence"], "medium")
        self.assertEqual(flows["win_back"]["status"], "missing")
        self.assertEqual(out["summary"], {"live": 2, "weak": 2, "stopped": 1, "draft": 1, "missing": 2})

    def test_long_wait_purchase_flow_is_replenishment_not_post_purchase(self):
        _, flows = full()
        repl = flows["replenishment"]
        self.assertEqual(repl["status"], "live")
        self.assertEqual(repl["scenarios"][0]["channels"], ["email", "push"])
        self.assertEqual(repl["scenarios"][0]["first_message_wait_hours"], 720)
        self.assertEqual([s["id"] for s in flows["post_purchase"]["scenarios"]], ["sc-thanks"])

    def test_disconnected_trigger_makes_live_flow_weak(self):
        _, flows = full()
        pp = flows["post_purchase"]
        self.assertEqual(pp["status"], "weak")
        self.assertIn("trigger isn't connected to the flow", pp["scenarios"][0]["problems"])
        self.assertIn("no message step on a connected path", pp["scenarios"][0]["problems"])

    def test_name_only_and_unfetched_are_unconfirmed(self):
        out, flows = full()
        ids = {(u["flow"], u["id"]) for u in out["unconfirmed"]}
        self.assertIn(("welcome", "sc-hello"), ids)
        self.assertIn(("sunset", "sc-sunset"), ids)
        self.assertNotIn("sc-hello", [s["id"] for s in flows["welcome"]["scenarios"]])
        self.assertNotIn(("welcome", "sc-welcome"), ids)  # fetched, so not "not checked"

    def test_revenue_at_stake_and_priority(self):
        out, flows = full("--audience", f"win_back={FIX / 'audience_winback.json'}",
                          "--audience", f"birthday={FIX / 'audience_birthday.json'}",
                          "--audience", "cart_abandonment=2,000", "--audience", "browse_abandonment=3000",
                          "--audience", "sunset=10", "--audience", "welcome=900", "--aov", "$80")
        wb = flows["win_back"]
        self.assertEqual(wb["monthly_audience"], 2000)  # 1500 + "500" rows added up
        self.assertAlmostEqual(wb["at_stake_monthly"], 2000 * 0.4 * 0.02 * 80)
        self.assertEqual(flows["birthday"]["monthly_audience"], 1000)  # 12,000 / 12 months
        self.assertAlmostEqual(flows["cart_abandonment"]["at_stake_monthly"], 2000 * 0.4 * 0.05 * 80 * 0.5)
        self.assertEqual(flows["welcome"]["at_stake_monthly"], 0)  # live
        self.assertEqual(flows["welcome"]["priority"], "none")
        self.assertIsNone(flows["sunset"]["value_monthly"])  # not a revenue flow
        self.assertEqual(flows["sunset"]["priority"], "low")  # under min_monthly_audience
        self.assertAlmostEqual(out["total_at_stake_monthly"], 1280 + 960 + 1600 + 960)
        self.assertEqual(flows["cart_abandonment"]["priority"], "high")
        self.assertEqual(flows["browse_abandonment"]["priority"], "medium")
        self.assertEqual(flows["win_back"]["handoff"], "engagement-scenario-builder")
        self.assertEqual(flows["birthday"]["handoff"], "scenario-qa")

    def test_reachable_override_and_no_aov(self):
        _, flows = full("--audience", "win_back=1000", "--reachable", "1", "--aov", "10")
        self.assertAlmostEqual(flows["win_back"]["at_stake_monthly"], 1000 * 1 * 0.02 * 10)
        out, flows = full("--audience", "win_back=1000")
        self.assertIsNone(flows["win_back"]["value_monthly"])
        self.assertIsNone(out["total_at_stake_monthly"])

    def test_deterministic(self):
        a, _ = full("--audience", "win_back=1000", "--aov", "50")
        b, _ = full("--audience", "win_back=1000", "--aov", "50")
        self.assertEqual(a, b)

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(SCRIPT), "--scenario", ALL, "--out", "coverage.json"],
                               cwd=tmp, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stdout)
            saved = json.loads((Path(tmp) / "coverage.json").read_text(encoding="utf-8"))
        self.assertTrue(json.loads(r.stdout)["ok"])
        self.assertEqual(len(saved["flows"]), 8)

    def test_errors(self):
        code, out = run("--scenario", str(FIX / "error.json"))
        self.assertEqual(code, 1)
        self.assertIn("Forbidden", out["error"])
        code, out = run("--scenario", str(FIX / "missing.json"))
        self.assertEqual(code, 1)
        self.assertIn("can't read", out["error"])
        code, out = run("--scenario", str(FIX / "scenario_list.json"))
        self.assertEqual(code, 1)
        self.assertIn("no scenario definition", out["error"])
        code, out = run("--audience", "loyalty=10")
        self.assertEqual(code, 1)
        self.assertIn("unknown flow", out["error"])
        code, out = run("--audience", "win_back=lots")
        self.assertEqual(code, 1)
        code, out = run("--scenario", ALL, "--out", str(FIX / "no-such-dir" / "x.json"))
        self.assertEqual(code, 1)
        self.assertIn("can't write", out["error"])


if __name__ == "__main__":
    unittest.main()
