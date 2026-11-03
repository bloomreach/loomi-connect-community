import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/engagement-weblayer-qa"
SCRIPT = SKILL / "scripts/weblayer_checks.py"
FX = ROOT / "tests/fixtures/engagement/weblayer_qa"
NOW = "2026-11-03T00:00:00Z"


def run(path, *args):
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPT), str(path), "--now", NOW, *args],
                              cwd=tmp, capture_output=True, text=True, encoding="utf-8")


def check(data):
    """Run the checks on a banner given as a dict; return the parsed result."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "banner.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        r = subprocess.run([sys.executable, str(SCRIPT), str(p), "--now", NOW], cwd=tmp, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr + r.stdout
    return json.loads(r.stdout)


def fixture(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def details(result, variant=None):
    if variant is None:
        return [f["detail"] for f in result["banner_findings"]]
    return [f["detail"] for f in result["variants"][variant]["findings"]]


def severity(result, variant, text):
    hits = [f["severity"] for f in result["variants"][variant]["findings"] if text in f["detail"]]
    assert hits, f"no finding containing {text!r}"
    return hits[0]


class WeblayerChecksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.broken = check(fixture("banner_broken.json"))

    def test_help(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0)
        self.assertIn("search_banners", r.stdout)

    def test_clean_banner_is_go(self):
        r = check(fixture("banner_clean.json"))
        self.assertEqual(r["verdict"], "GO")
        self.assertEqual(r["counts"], {"blocker": 0, "warning": 0, "nitpick": 0})
        v = r["variants"][0]
        self.assertEqual(v["skeleton"], "utils")
        self.assertEqual(v["findings"], [])
        # Parameters in links are filled in with the current values before they're listed.
        self.assertEqual([l["url"] for l in v["links_to_load"]], ["https://cdn.shop.invalid/hero.png", "https://www.shop.invalid/sale"])
        self.assertTrue(all(l["expected"] for l in v["external_loads"]))

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(SCRIPT), str(FX / "banner_broken.json"), "--now", NOW, "--out", "qa.json"],
                               cwd=tmp, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["verdict"], "NO-GO")
            self.assertEqual(json.loads((Path(tmp) / "qa.json").read_text(encoding="utf-8"))["verdict"], "NO-GO")

    def test_error_response(self):
        r = run(FX / "banner_denied.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Loomi Connect returned an error: [ACCESS_DENIED]", r.stdout)

    def test_not_a_banner(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "list.json"
            p.write_text(json.dumps({"result": {"success": True, "data": []}}), encoding="utf-8")
            r = run(p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a search_banners detail result", r.stdout)

    def test_banner_level(self):
        d = details(self.broken)
        self.assertIn("Enabled variants' traffic adds up to 90%, not 100%", d)
        self.assertIn("No pages are included, so the weblayer may show nowhere", d)
        self.assertTrue(any(x.startswith("The schedule ended on 2025-06-15") for x in d))
        self.assertEqual(self.broken["verdict"], "NO-GO")

    def test_disabled_variant_does_not_count(self):
        b = fixture("banner_broken.json")
        data = b["result"]["data"]
        data["variants"] = [fixture("banner_clean.json")["result"]["data"]["variants"][0] | {"percentage": 100}, data["variants"][0] | {"enabled": False}]
        data["trigger"]["include_pages"] = [{"type": "contains", "value": "/sale/"}]
        data["date_filter"]["to"] = 1830000000
        r = check(b)
        self.assertTrue(r["variants"][1]["findings"])
        self.assertEqual(r["verdict"], "GO")

    def test_skeleton_rules(self):
        d = " | ".join(details(self.broken, 0))
        for text in ("doesn't end with return { remove: removeBanner }", "`utils` is redeclared",
                     "utils.setConfig() is never called", "looks for '.popup', but no HTML element has that class",
                     "<html>, <head> or <body>", "isn't the last line of createBanner()",
                     "outside loadScript()", "built by hand", "handleCloseButtonClick"):
            self.assertIn(text, d)
        self.assertEqual(self.broken["variants"][0]["skeleton"], "utils")

    def test_unsafe_code_and_leftovers(self):
        self.assertEqual(severity(self.broken, 0, "Uses eval()"), "blocker")
        self.assertEqual(severity(self.broken, 0, "Uses document.write()"), "blocker")
        self.assertEqual(severity(self.broken, 0, "put a value in as HTML"), "warning")
        self.assertEqual(severity(self.broken, 0, "`debugger`"), "warning")
        self.assertEqual(severity(self.broken, 0, "console.log"), "nitpick")
        self.assertEqual(severity(self.broken, 0, "plain value"), "warning")
        self.assertEqual(self.broken["variants"][0]["storage_access"], ["localStorage"])

    def test_parameters(self):
        self.assertEqual(severity(self.broken, 0, "isn't closed with ]]"), "blocker")
        self.assertEqual(severity(self.broken, 0, "'NoJson' lacks isJsonParam"), "warning")
        self.assertEqual(severity(self.broken, 0, "'Count' is a number with a non-numeric default"), "warning")
        self.assertEqual(severity(self.broken, 0, "'Quote' has a default containing a double quote"), "warning")
        self.assertEqual(severity(self.broken, 0, "'Count' is used with different types"), "warning")
        self.assertEqual(severity(self.broken, 0, "'Link' has unknown type 'url'"), "nitpick")
        self.assertEqual(severity(self.broken, 0, "not used in the code: OldParam"), "nitpick")
        self.assertEqual(severity(self.broken, 0, "no image set: Hero"), "nitpick")
        self.assertEqual(severity(self.broken, 0, "image URL(s) are hard-coded"), "warning")
        self.assertEqual(severity(self.broken, 0, "copy are hard-coded"), "nitpick")
        self.assertEqual(severity(self.broken, 0, "colour(s) are hard-coded, e.g. #ff0000"), "nitpick")
        self.assertEqual(severity(self.broken, 0, "Font family hard-coded: Comic Sans MS"), "nitpick")

    def test_triggering_code(self):
        self.assertIn("showAfter", " ".join(details(self.broken, 0)))
        self.assertEqual(severity(self.broken, 0, "Listeners that usually mean triggering code: mouseout"), "warning")
        self.assertEqual(severity(self.broken, 1, "PARAM_trigger"), "warning")

    def test_auto_close_is_not_triggering(self):
        b = fixture("banner_clean.json")
        b["result"]["data"]["variants"][0]["params"]["AutoHideDelay"] = "5000"
        b["result"]["data"]["variants"][0]["params"]["removeAfter"] = "0"
        r = check(b)
        self.assertFalse([d for d in details(r, 0) if "Triggering" in d])

    def test_jinja(self):
        self.assertEqual(severity(self.broken, 0, "{% if %} is never closed"), "blocker")
        self.assertEqual(severity(self.broken, 0, "{{ customer.first_name }} has no fallback"), "warning")
        self.assertEqual(severity(self.broken, 0, "default() without true"), "warning")
        self.assertEqual(severity(self.broken, 0, "loop over an aggregate has no guard"), "warning")

    def test_links(self):
        self.assertEqual(severity(self.broken, 0, "javascript: URL"), "blocker")
        self.assertEqual(severity(self.broken, 0, "placeholder (empty or '#')"), "warning")
        self.assertEqual(severity(self.broken, 0, "no https:// scheme"), "warning")
        self.assertEqual(severity(self.broken, 0, "placeholder host (example.com)"), "warning")
        self.assertEqual(severity(self.broken, 0, "('todo' in the path)"), "warning")
        self.assertEqual(severity(self.broken, 0, "uses http://"), "warning")
        urls = [l["url"] for l in self.broken["variants"][0]["links_to_load"]]
        self.assertNotIn("javascript:alert(1)", urls)
        self.assertIn("https://example.com/landing", urls)

    def test_closing_and_accessibility(self):
        self.assertEqual(severity(self.broken, 0, "close button has no aria-label"), "warning")
        self.assertEqual(severity(self.broken, 0, "image(s) have no alt attribute"), "nitpick")
        # A fixed bar with no close button is a warning; a full-screen one is a blocker.
        self.assertEqual(severity(self.broken, 1, "fixed weblayer with no close button"), "warning")
        b = fixture("banner_broken.json")
        b["result"]["data"]["variants"][1]["style"] = ".promo-bar { position: fixed; inset: 0; }"
        self.assertEqual(severity(check(b), 1, "full-screen pop-up with no close button"), "blocker")

    def test_legacy_template(self):
        v = self.broken["variants"][1]
        self.assertEqual(v["skeleton"], "legacy")
        self.assertEqual(severity(self.broken, 1, "older template"), "nitpick")
        self.assertEqual(severity(self.broken, 1, "Nothing inserts the weblayer"), "blocker")
        self.assertEqual(severity(self.broken, 1, "No banner events"), "warning")
        # An inline remove function is a valid ending.
        self.assertFalse([d for d in details(self.broken, 1) if "return { remove" in d])

    def test_external_loads(self):
        loads = self.broken["variants"][0]["external_loads"]
        self.assertIn({"kind": "fetch", "target": "https://collector.analytics.invalid/hit", "expected": False}, loads)
        self.assertEqual(severity(self.broken, 0, "external load(s)"), "warning")

    def test_size(self):
        b = fixture("banner_clean.json")
        v = b["result"]["data"]["variants"][0]
        v["style"] += "\n.bg { background: url(data:image/png;base64," + "A" * 220000 + "); }"
        r = check(b)
        self.assertEqual(severity(r, 0, "inline data: URI(s) over 50 KB"), "warning")
        self.assertEqual(severity(r, 0, "The code is"), "nitpick")

    def test_every_page_and_missing_schedule(self):
        b = fixture("banner_clean.json")
        data = b["result"]["data"]
        data["trigger"]["include_pages"] = [{"type": "any"}]
        del data["date_filter"]
        r = check(b)
        self.assertIn("Shows on every page, including checkout and account pages", details(r))
        self.assertTrue(any(n.startswith("schedule (not in the banner details") for n in r["not_checked"]))
        data["date_filter"] = {"enabled": True, "from": 1790000000}
        self.assertIn("The schedule has no end date", details(check(b)))

    def test_masks_emails_in_excerpts(self):
        b = fixture("banner_clean.json")
        b["result"]["data"]["variants"][0]["html"] += '<a href="https://www.shop.invalid/test?to=jane.doe@shop.invalid">x</a>'
        out = json.dumps(check(b)["variants"][0]["findings"])
        self.assertNotIn("jane.doe@", out)
        self.assertIn("<email>", out)

    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        keys = set(rules) - {"about", "notes"}
        self.assertEqual(keys, set(rules["notes"]))


def load_module():
    import importlib.util
    sys.dont_write_bytecode = True  # no __pycache__ in the skill folder
    spec = importlib.util.spec_from_file_location("weblayer_checks", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class HelperTest(unittest.TestCase):
    def test_aggregate_loop_guard(self):
        mod = load_module()
        self.assertTrue(mod.unguarded_aggregate_loop("{% set c = aggregates['a'] %}{% for i in c %}{% endfor %}"))
        self.assertTrue(mod.unguarded_aggregate_loop("{{ 'None' }}" + "x" * 500 + "{% for i in aggregates['a'] %}"))
        self.assertFalse(mod.unguarded_aggregate_loop(
            "{% set c = aggregates['a'] %}{% if c and c != 'None' %}{% for i in c %}{% endfor %}{% endif %}"))
        self.assertFalse(mod.unguarded_aggregate_loop("{% for i in items %}{% endfor %}"))

    def test_allowlist_matches_hosts_not_substrings(self):
        mod = load_module()
        for target in ["/brstatic/utils.js", "https://api.exponea.com", "https://api.exponea.com/track",
                       "https://cdn.jsdelivr.net/npm/intl-tel-input@17/build/js/utils.js"]:
            self.assertTrue(mod.expected_load(target), target)
        for target in ["https://evil.invalid/brstatic/x.js", "https://api.exponea.com.evil.invalid/x",
                       "https://cdn.jsdelivr.net/npm/other@1/x.js", "http://api.exponea.com/x", "/other/x.js"]:
            self.assertFalse(mod.expected_load(target), target)


if __name__ == "__main__":
    unittest.main()
