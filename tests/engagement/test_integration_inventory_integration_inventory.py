"""Tests for integration-inventory's integration_inventory.py. The fixtures are synthetic; every secret in them
contains FAKE, and none of them may reach the output."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/integration-inventory"
SCRIPT = SKILL / "scripts/integration_inventory.py"
FIX = ROOT / "tests/fixtures/engagement/integration-inventory"
SECRETS = ["tok-FAKE-1234567890abcdef", "FAKE-token-abc123", "sk_live_FAKE0123456789abcd", "FAKEdXNlcjpwYXNz",
           "FAKEsig123", "key-FAKE-0123456789abcdef", "FAKE-body-123", "FAKE-user"]


def run(*args, cwd=None):
    """Run the script by its full path from a fresh working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=cwd or tmp, capture_output=True,
                           text=True, encoding="utf-8", timeout=60)
        if cwd is None:
            assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def inputs():
    args = ["--integrations", FIX / "integrations.json", "--api-triggers", FIX / "api_triggers.json",
            "--variables", FIX / "variables.json"]
    for name in ("trigger_order_shipped.json", "trigger_untitled.json", "trigger_legacy.json"):
        args += ["--api-trigger-detail", FIX / name]
    for kind, name in (("scenario", "scenarios.json"), ("scenario", "scenario_order_sync.json"),
                       ("scenario", "scenario_shipping_notice.json"), ("scenario", "scenario_draft_hooks.json"),
                       ("email", "email_campaigns.json"), ("email", "email_weekly_news.json"),
                       ("banner", "banners.json"), ("banner", "banner_promo_bar.json")):
        args += ["--assets", f"{kind}={FIX / name}"]
    return args + ["--denied", "sms"]


def full():
    r = run(*inputs())
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout, json.loads(r.stdout)


def finding(out, area, item, issue_start):
    return next((f for f in out["findings"] if f["area"] == area and f["item"] == item
                 and f["issue"].startswith(issue_start)), None)


class InventoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text, cls.out = full()

    def test_secrets_never_reach_the_output(self):
        for s in SECRETS:
            self.assertNotIn(s, self.text)
        self.assertNotIn("FAKE", self.text)
        self.assertNotIn("Example Brand", self.text)  # variable values are described, never shown
        self.assertNotIn("/orders", self.text)  # URL paths and query strings are dropped
        self.assertIsNone(re.search(r"\?[^\s\"]*=", self.text), "a query string reached the output")
        self.assertNotIn("Pat Example", self.text)

    def test_webhook_descriptions_show_host_only(self):
        hooks = {w["step"]: w for w in self.out["webhooks"]}
        sync = hooks["Send order"]
        self.assertEqual(sync["host"], "hooks.partner.example")
        self.assertIn("an auth header", sync["description"])
        self.assertIn("'CRM auth'", sync["description"])
        self.assertEqual(sync["flags"], ["credential in URL", "credential in step headers"])
        old = hooks["Old hook"]
        self.assertEqual(old["flags"], ["integration not found", "empty credential parameter", "plain HTTP"])

    def test_webhook_priorities_follow_liveness(self):
        self.assertEqual(finding(self.out, "webhook", "Order sync / step 2", "A credential is written")["priority"], "high")
        self.assertEqual(finding(self.out, "webhook", "Draft hooks / step 5", "Webhook step authenticates")["priority"], "medium")

    def test_integrations(self):
        rows = {i["id"][-2:]: i for i in self.out["integrations"]}
        self.assertEqual(rows["04"]["references"][0]["how"], "webhook authentication")
        self.assertIn("duplicate", rows["01"]["flags"])
        self.assertIn("no reference found", rows["05"]["flags"])
        self.assertEqual(rows["03"]["flags"], [])  # storage usage isn't visible, so never "unused"
        self.assertEqual(rows["06"]["name"], "Partner https://api.partner.example/...")

    def test_api_triggers(self):
        rows = {t["name"]: t for t in self.out["api_triggers"] if t["event_type"] is not None or t["name"] != "Order shipped"}
        self.assertIn("archived but used", rows["Legacy hook"]["flags"])
        self.assertEqual(rows["Untitled API trigger"]["flags"], ["no event type", "unused", "test name"])
        self.assertEqual(finding(self.out, "api_trigger", "Legacy hook", "Archived")["priority"], "high")
        self.assertIsNotNone(finding(self.out, "api_trigger", "Order shipped / Order shipped", "2 API triggers"))

    def test_variables(self):
        rows = {v["reference"]: v for v in self.out["variables"]}
        self.assertEqual(rows["partner_api_secret"]["value"], "looks like a key")
        self.assertEqual(rows["Basic_auth_for_API"]["flags"], ["stored credential"])
        self.assertEqual(rows["logo_url"]["value"], "a URL on cdn.example.com")
        self.assertEqual(rows["catalog_id"]["value"], "an object ID")
        self.assertEqual(rows["brand_name"]["references"][0]["name"], "Weekly news")
        self.assertEqual(finding(self.out, "variable", "empty_used", "Empty, but")["priority"], "high")
        self.assertEqual(finding(self.out, "variable", "missing_var", "Used in 1")["priority"], "high")
        self.assertIsNotNone(finding(self.out, "variable", "BrandName / brand_name", "Variables whose names"))

    def test_sorted_and_counted(self):
        order = {"high": 0, "medium": 1, "low": 2}
        prios = [order[f["priority"]] for f in self.out["findings"]]
        self.assertEqual(prios, sorted(prios))
        self.assertEqual(sum(self.out["summary"].values()), len(self.out["findings"]))
        self.assertEqual(self.out["checked"]["denied"], ["sms"])

    def test_deterministic(self):
        self.assertEqual(full()[0], self.text)

    def test_tool_error_is_not_nothing_found(self):
        r = run("--integrations", FIX / "denied.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("don't treat it as 'nothing found'", r.stdout)

    def test_bad_input(self):
        self.assertEqual(run().returncode, 1)
        self.assertEqual(run("--variables", FIX / "nope.json").returncode, 1)
        self.assertEqual(run("--variables", FIX / "variables.json", "--assets", f"widget={FIX / 'banners.json'}").returncode, 1)
        self.assertEqual(run("--variables", FIX / "variables.json", "--assets", "banner").returncode, 1)

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run(*inputs(), "--out", "inventory.json", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((Path(tmp) / "inventory.json").read_text(encoding="utf-8"), r.stdout)
            bad = run(*inputs(), "--out", str(Path(tmp) / "missing" / "i.json"), cwd=tmp)
            self.assertEqual(bad.returncode, 1)


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertTrue(rules.get("about"))
        keys = set(rules) - {"about", "notes"}
        self.assertEqual(sorted(keys - set(rules["notes"])), [])
        self.assertEqual(sorted(set(rules["notes"]) - keys), [])


if __name__ == "__main__":
    unittest.main()
