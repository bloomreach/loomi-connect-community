"""Tests for klaviyo_to_bloomreach.py. They need a venv with beautifulsoup4 and jinja2:

    python3 plugins/loomi-engagement/skills/convert-klaviyo-email-to-bloomreach/scripts/klaviyo_to_bloomreach.py setup --venv /tmp/klvenv
    /tmp/klvenv/bin/pip install beautifulsoup4 jinja2
    KLAVIYO_TEST_VENV=/tmp/klvenv python3 -m unittest discover -s tests -t .

Without KLAVIYO_TEST_VENV (or without the packages in it) they are skipped.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plugins/loomi-engagement/skills/convert-klaviyo-email-to-bloomreach/scripts/klaviyo_to_bloomreach.py"
FX = ROOT / "tests/fixtures/engagement/klaviyo"
VENV = os.environ.get("KLAVIYO_TEST_VENV")


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


@unittest.skipUnless(venv_ready(), "set KLAVIYO_TEST_VENV to a venv with beautifulsoup4 and jinja2")
class KlaviyoToBloomreachTest(unittest.TestCase):
    def convert(self, export, mapping=None, meta=None):
        """Run analyze then build from a temp working folder; return (build result, email.html)."""
        with tempfile.TemporaryDirectory() as tmp:
            mp = FX / "mapping.json"
            if mapping is not None:
                mp = Path(tmp) / "mapping.json"
                mp.write_text(json.dumps(mapping))
            mt = FX / "meta_now.json"
            if meta is not None:
                mt = Path(tmp) / "meta.json"
                mt.write_text(json.dumps(meta))
            run = lambda *a: subprocess.run([sys.executable, str(SCRIPT), *map(str, a), "--venv", VENV],
                                            cwd=tmp, capture_output=True, text=True)
            r = run("analyze", FX / export, "--out-dir", "out")
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            r = run("build", "--model", "out/model.json", "--mapping", mp, "--meta", mt, "--out-dir", "out")
            result = json.loads(r.stdout)
            html = (Path(tmp) / "out" / "email.html").read_text(encoding="utf-8")
        return result, html

    def test_help(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--help", "--venv", VENV], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_plain_copy_mentioning_event_is_not_an_error(self):
        result, _ = self.convert("export_plain_event_copy.html")
        self.assertTrue(result["ok"], result["errors"])

    def test_event_data_with_now_trigger_is_an_error(self):
        mapping = json.loads((FX / "mapping.json").read_text())
        mapping.pop("event_list_aggregates")
        result, html = self.convert("export_cart.html", mapping=mapping)
        self.assertIn("event.product_list", html)
        self.assertTrue(any("trigger-event data" in e for e in result["errors"]))

    def test_loop_variable_inside_catalog_loop(self):
        result, html = self.convert("export_cart.html")
        self.assertIn("{{ product.Quantity }}", html)
        self.assertNotIn("line.Quantity", html)
        self.assertIn("{{ item.title }}", html)
        self.assertTrue(any("loop variable 'line'" in w for w in result["warnings"]))

    def test_attributes_escaped(self):
        result, html = self.convert("export_cart.html")
        self.assertIn('alt="Tom &amp; &quot;Jerry&quot; {{ first_name }}"', html)
        self.assertIn('href="https://shop.example/sale?a=1&amp;b=2"', html)
        self.assertTrue(any("image alt attribute" in w for w in result["warnings"]))

    def test_subject_translated_once(self):
        result, html = self.convert("export_cart.html")
        # one {{ first_name }} in the body copy and one in the subject
        self.assertEqual(result["changes"]["{{ first_name }} shorthand -> customer property"], 2)
        self.assertIn("<title>Hi {{ customer.first_name | default('friend', true) }}, you left something</title>", html)

    def render(self, html, context):
        """Run render-check on built HTML with a context; return its JSON result."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "email.html").write_text(html, encoding="utf-8")
            (Path(tmp) / "ctx.json").write_text(json.dumps(context), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), "render-check", "--html", "email.html", "--context", "ctx.json",
                                "--venv", VENV], cwd=tmp, capture_output=True, text=True)
        return json.loads(r.stdout)

    def test_default_replaces_empty_values(self):
        # Klaviyo's default replaces any empty value; Bloomreach's only does with true.
        _, html = self.convert("export_cart.html")
        self.assertIn("customer.first_name | default('there', true)", html)
        out = self.render(html, {"customer": {"first_name": None}})
        self.assertTrue(out["ok"], out)
        # The body line has a default in the export; the subject line doesn't, so it's left as is.
        self.assertIn("Hi there, your cart", out["visible_text_preview"])
        self.assertNotIn("Hi None, your cart", out["visible_text_preview"])

    def test_fallback_added_where_klaviyo_had_no_default(self):
        # Klaviyo prints an empty property as nothing; Bloomreach prints None, so the subject gets a fallback.
        result, html = self.convert("export_cart.html")
        self.assertIn("{{ customer.first_name | default('friend', true) }}, you left something", html)
        self.assertEqual(result["changes"]["{{ customer.first_name }} with no fallback -> default('friend', true)"], 1)
        # The body line already had a default, which is kept as it was.
        self.assertIn("customer.first_name | default('there', true)", html)
        self.assertNotIn("default('there', true) | default(", html)
        out = self.render(html, {"customer": {"first_name": None}})
        self.assertNotIn("None", out["visible_text_preview"])

    def test_fallbacks_from_mapping_and_for_other_properties(self):
        mapping = json.loads((FX / "mapping.json").read_text(encoding="utf-8"))
        mapping["fallbacks"] = {"first_name": "valued customer"}
        meta = json.loads((FX / "meta_now.json").read_text(encoding="utf-8"))
        meta["subject"] = "Hi {{ first_name }}, {{ person.last_name|upper }} family"
        _, html = self.convert("export_cart.html", mapping=mapping, meta=meta)
        self.assertIn("<title>Hi {{ customer.first_name | default('valued customer', true) }}, "
                      "{{ customer.last_name | default('', true) | upper }} family</title>", html)

    def test_cart_loop_guards_empty_aggregate(self):
        # An empty aggregate renders as the string 'None'; looping over it would iterate its letters.
        _, html = self.convert("export_cart.html")
        self.assertIn("aggregates['aaaaaaaaaaaaaaaaaaaaaaaa'] != 'None'", html)
        out = self.render(html, {"aggregates": {"aaaaaaaaaaaaaaaaaaaaaaaa": "None"}, "catalogs": {"products": {}}})
        self.assertTrue(out["ok"], out)


if __name__ == "__main__":
    unittest.main()
