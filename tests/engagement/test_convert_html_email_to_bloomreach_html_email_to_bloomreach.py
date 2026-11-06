"""Tests for html_email_to_bloomreach.py. They need a venv with beautifulsoup4 and jinja2:

    python3 plugins/loomi-engagement/skills/convert-html-email-to-bloomreach/scripts/html_email_to_bloomreach.py setup --venv /tmp/htvenv
    /tmp/htvenv/bin/pip install beautifulsoup4 jinja2
    HTML_EMAIL_TEST_VENV=/tmp/htvenv python3 -m unittest discover -s tests -t .

KLAVIYO_TEST_VENV works too (CI creates that one; it holds the same packages). Without either, or without the
packages in it, the tests that run the converter are skipped.

The fixtures in tests/fixtures/engagement/html-email are synthetic exports, one per ESP syntax.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plugins/loomi-engagement/skills/convert-html-email-to-bloomreach/scripts/html_email_to_bloomreach.py"
FX = ROOT / "tests/fixtures/engagement/html-email"
VENV = os.environ.get("HTML_EMAIL_TEST_VENV") or os.environ.get("KLAVIYO_TEST_VENV")


def venv_ready():
    if not VENV:
        return False
    py = Path(VENV) / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")
    if not py.exists():
        return False
    r = subprocess.run([str(py), "-c", "import bs4, jinja2"], capture_output=True)
    return r.returncode == 0


class HelpWithoutPackagesTest(unittest.TestCase):
    def test_help(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(SCRIPT), "--help"], cwd=tmp, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("render-check", r.stdout)

    def test_venv_inside_skill_folder_is_refused(self):
        bad = SCRIPT.parent.parent / ".venv"
        r = subprocess.run([sys.executable, str(SCRIPT), "setup", "--venv", str(bad)], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not inside the skill", r.stdout + r.stderr)
        self.assertFalse(bad.exists())


@unittest.skipUnless(venv_ready(), "set HTML_EMAIL_TEST_VENV to a venv with beautifulsoup4 and jinja2")
class HtmlEmailToBloomreachTest(unittest.TestCase):
    def run_script(self, tmp, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args), "--venv", VENV],
                              cwd=tmp, capture_output=True, text=True)

    def analyze(self, export, tmp):
        r = self.run_script(tmp, "analyze", FX / export, "--out-dir", "out")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return json.loads(r.stdout)

    def convert(self, export, mapping=None, meta=None, render=False):
        """analyze + build (+ render-check) in a temp working folder; returns (report, build result, html, render)."""
        with tempfile.TemporaryDirectory() as tmp:
            mp = FX / (f"{export[:-5]}.mapping.json" if (FX / f"{export[:-5]}.mapping.json").exists() else "mapping.json")
            if mapping is not None:
                mp = Path(tmp) / "mapping.json"
                mp.write_text(json.dumps(mapping))
            mt = FX / "meta.json"
            if meta is not None:
                mt = Path(tmp) / "meta.json"
                mt.write_text(json.dumps(meta))
            report = self.analyze(export, tmp)
            r = self.run_script(tmp, "build", "--model", "out/model.json", "--mapping", mp, "--meta", mt, "--out-dir", "out")
            result = json.loads(r.stdout)
            self.assertEqual(r.returncode, 0 if result["ok"] else 1)
            html = (Path(tmp) / "out" / "email.html").read_text(encoding="utf-8")
            payload = json.loads((Path(tmp) / "out" / "payload.json").read_text(encoding="utf-8"))
            rendered = None
            if render:
                r = self.run_script(tmp, "render-check", "--html", "out/email.html", "--context", FX / "render-context.json")
                rendered = json.loads(r.stdout)
        return report, result, html, payload, rendered

    # ---- detection and tokens -------------------------------------------------------------
    def test_detects_each_esp(self):
        expected = {"mailchimp.html": "mailchimp", "sfmc.html": "sfmc", "hubspot.html": "hubspot", "braze.html": "braze",
                    "iterable.html": "iterable", "activecampaign.html": "activecampaign", "plain.html": "plain"}
        with tempfile.TemporaryDirectory() as tmp:
            for export, esp in expected.items():
                self.assertEqual(self.analyze(export, tmp)["esp_guess"], esp, export)

    def test_klaviyo_export_points_to_the_klaviyo_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self.run_script(tmp, "analyze", ROOT / "tests/fixtures/engagement/klaviyo/export_cart.html", "--out-dir", "out")
        self.assertEqual(json.loads(r.stdout)["recommended_skill"], "convert-klaviyo-email-to-bloomreach")

    def test_comment_and_title_tokens_are_not_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tokens = [t["token"] for t in self.analyze("mailchimp.html", tmp)["tokens"]]
        self.assertNotIn("*|MC:SUBJECT|*", tokens)            # only in <title>
        self.assertNotIn("*|IF:MC_PREVIEW_TEXT|*", tokens)    # only in an HTML comment

    def test_ampscript_logic_needs_a_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self.analyze("sfmc.html", tmp)
        needs = {t["token"] for t in report["tokens"] if t["needs_mapping"]}
        self.assertIn('%%[ IF @tier == "Gold" THEN ]%%', needs)
        self.assertIn("%%=v(@firstName)=%%", needs)
        self.assertNotIn("%%emailaddr%%", needs)

    # ---- translation ----------------------------------------------------------------------
    def test_mailchimp_converts_and_renders(self):
        report, result, html, payload, rendered = self.convert("mailchimp.html", render=True)
        self.assertTrue(result["ok"], result["errors"])
        self.assertIn("{% if customer.first_name %}", html)
        self.assertIn("{{ customer.loyalty_tier | default('', true) }}", html)   # *|TIER|* via custom_properties
        self.assertIn("{{ consent.page }}", html)
        self.assertIn("{{ email.view }}", html)
        self.assertNotIn("*|", html)
        self.assertTrue(rendered["ok"], rendered)
        self.assertEqual(rendered["undefined_references"], [])
        self.assertIn("Hi Alex,", rendered["visible_text_preview"])
        self.assertIn("Your loyalty tier: Gold", rendered["visible_text_preview"])
        self.assertIn("AUTUMN20", report["hardcoded_codes"])

    def test_every_esp_fixture_builds(self):
        for export in ("sfmc.html", "hubspot.html", "braze.html", "iterable.html", "activecampaign.html"):
            with self.subTest(export=export):
                _, result, html, _, rendered = self.convert(export, render=True)
                self.assertTrue(result["ok"], result["errors"])
                self.assertTrue(rendered["ok"], rendered)
                self.assertEqual(rendered["leftover_tags"], [])
                self.assertIn("Alex", rendered["visible_text_preview"])
                for leftover in ("%%", "${", "{{#", "contact.", "%FIRSTNAME%"):
                    self.assertNotIn(leftover, html)

    def test_unmapped_token_blocks_the_build(self):
        mapping = json.loads((FX / "sfmc.mapping.json").read_text())
        del mapping["tokens"]["%%[ ELSE ]%%"]
        _, result, _, _, _ = self.convert("sfmc.html", mapping=mapping)
        self.assertFalse(result["ok"])
        self.assertTrue(any("No translation for source token '%%[ ELSE ]%%'" in e for e in result["errors"]), result["errors"])

    def test_missing_unsubscribe_blocks_the_build(self):
        _, result, _, _, _ = self.convert("plain.html")
        self.assertFalse(result["ok"])
        self.assertTrue(any("unsubscribe" in e.lower() for e in result["errors"]))
        self.assertTrue(any("empty" in w for w in result["warnings"]))  # the empty "Directions" link

    def test_missing_company_address_blocks_the_build(self):
        mapping = json.loads((FX / "mapping.json").read_text())
        mapping["organization"].pop("full_address")
        _, result, _, _, _ = self.convert("mailchimp.html", mapping=mapping)
        self.assertFalse(result["ok"])
        self.assertTrue(any("full address" in e for e in result["errors"]), result["errors"])

    def test_condition_split_across_blocks_is_an_error(self):
        mapping = json.loads((FX / "sfmc.mapping.json").read_text())
        mapping["tokens"]["%%[ ELSE ]%%"] = "{% endif %}{% endif %}"   # unbalanced on purpose
        _, result, _, _, _ = self.convert("sfmc.html", mapping=mapping)
        self.assertFalse(result["ok"])
        self.assertTrue(any("Jinja syntax error" in e for e in result["errors"]), result["errors"])

    def test_event_data_with_now_trigger_is_an_error(self):
        mapping = json.loads((FX / "mapping.json").read_text())
        mapping["tokens"] = {"*|TIER|*": "{{ event.tier }}"}
        _, result, _, _, _ = self.convert("mailchimp.html", mapping=mapping)
        self.assertTrue(any("trigger-event data" in e for e in result["errors"]), result["errors"])

    def test_mapping_token_wins_over_built_in_rule(self):
        mapping = json.loads((FX / "mapping.json").read_text())
        mapping["tokens"] = {"*|FNAME|*": "{{ customer.nickname | default('pal', true) }}"}
        _, result, html, _, _ = self.convert("mailchimp.html", mapping=mapping)
        self.assertTrue(result["ok"], result["errors"])
        self.assertIn("customer.nickname", html)

    # ---- layout ---------------------------------------------------------------------------
    def test_layout_and_payload(self):
        report, result, html, payload, _ = self.convert("mailchimp.html")
        self.assertEqual(report["block_types"].get("button"), 1)
        self.assertEqual(report["block_types"].get("social"), 1)
        bee = json.loads(payload["nodes"][1]["design"]["data"]["beefree_template"])
        types = [row["type"] for row in bee["page"]["rows"]]
        self.assertIn("two-columns-6-6-empty", types)
        self.assertEqual(payload["nodes"][1]["design"]["type"], "beefree")
        self.assertEqual(payload["nodes"][0]["type"], "now-trigger")
        # the rehosted logo is used; the image not in image_map is reported
        self.assertIn("https://cdn.example.com/media/logo.png", html)
        self.assertTrue(any("old ESP" in w for w in result["warnings"]))
        # tracking pixel and hidden preheader are not blocks
        self.assertNotIn("open.php", html)

    def test_inline_block_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.analyze("hubspot.html", tmp)
            model = json.loads((Path(tmp) / "out" / "model.json").read_text(encoding="utf-8"))
        self.assertTrue(any(len(r["columns"]) == 2 for r in model["rows"]))

    def test_jinja_inside_text_survives_html_parsing(self):
        mapping = json.loads((FX / "sfmc.mapping.json").read_text())
        mapping["tokens"]['%%[ IF @tier == "Gold" THEN ]%%'] = "{% if customer.orders > 1 and customer.loyalty_tier %}"
        _, result, html, _, _ = self.convert("sfmc.html", mapping=mapping)
        self.assertTrue(result["ok"], result["errors"])
        self.assertIn("{% if customer.orders > 1 and customer.loyalty_tier %}", html)


if __name__ == "__main__":
    unittest.main()
