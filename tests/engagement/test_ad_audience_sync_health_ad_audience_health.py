import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/ad-audience-sync-health"
SCRIPT = SKILL / "scripts/ad_audience_health.py"
FIX = ROOT / "tests/fixtures/engagement/ad-audience-sync-health"


def f(name):
    return str(FIX / name)


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=tmp, capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout


def full(*extra):
    code, out = run("--external", f("external.json"), "--segmentations", f("segmentations.json"),
                    "--segmentation-detail", f("seg_detail_1.json"), "--segmentation-detail", f("seg_detail_3.json"),
                    "--integrations", f("integrations.json"), "--consent-settings", f("consent_settings.json"),
                    "--scenario", f("scenario_1.json"), "--scenario", f("scenario_2.json"),
                    "--autosegments", f("autosegments.json"), "--autosegment-detail", f("autoseg_detail_1.json"),
                    "--autosegment-detail", f("autoseg_detail_2.json"), "--autosegment-detail", f("autoseg_detail_4.json"),
                    "--size", "ext1=0", "--size", "scn000000000000000000001:3=50", "--last-sync", "ext1=2026-11-03",
                    "--today", "2026-11-04", *extra)
    if code:
        raise AssertionError(out)
    return json.loads(out)


def kinds(item):
    return {x["kind"]: x["priority"] for x in item["findings"]}


def audience(out, key):
    return next(a for a in out["audiences"] if a["key"] == key)


class AdAudienceHealthTest(unittest.TestCase):
    def test_rules_every_key_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))

    def test_ads_destinations_and_consent_category(self):
        out = full()
        self.assertEqual([d["type"] for d in out["ads_destinations"]], ["facebook-ads", "google-adwords"])  # not the mail integration
        self.assertEqual(out["consent"]["advertising_categories"], ["advertising"])

    def test_ad_step_found_by_integration_id_and_path(self):
        out = full()
        a = audience(out, "scn000000000000000000001:3")
        self.assertEqual(a["matched_by"], "ads integration id")
        self.assertEqual(a["sources"], ["seg000000000000000000003"])
        self.assertEqual(a["consent"], ["newsletter"])  # from the segmentation detail, not advertising
        k = kinds(a)
        self.assertEqual(k["no_ad_consent"], "high")  # live scenario
        self.assertEqual(k["too_small"], "medium")
        self.assertEqual(a["min_size_rule_of_thumb"], 100)
        keys = {x["key"] for x in out["audiences"]}
        self.assertNotIn("scn000000000000000000001:4", keys)  # an email step is never an ad audience

    def test_duplicate_destination_and_source(self):
        out = full()
        self.assertEqual(out["duplicates"][0]["audiences"], ["scn000000000000000000001:3", "scn000000000000000000002:3"])
        b = audience(out, "scn000000000000000000002:3")
        self.assertNotIn("no_ad_consent", kinds(b))  # its own condition filters on advertising consent

    def test_external_segments(self):
        out = full()
        self.assertEqual(kinds(audience(out, "ext2"))["source_archived"], "high")
        self.assertEqual(kinds(audience(out, "ext1")), {"empty": "medium"})
        self.assertIn("no_linked_segmentation", kinds(audience(out, "ext3")))
        k = kinds(audience(out, "ext4"))
        self.assertEqual(k["failing"], "high")
        self.assertEqual(k["stale"], "medium")
        self.assertEqual(k["too_small"], "medium")  # 250 under the google rule of thumb
        self.assertEqual(k["no_ad_consent"], "medium")

    def test_autosegments(self):
        out = full()
        a = {x["id"]: kinds(x) for x in out["autosegments"]}
        self.assertNotIn("as4", a)  # archived
        self.assertEqual(a["as1"], {"failed": "medium"})
        self.assertEqual(a["as2"], {"stale": "low", "unused": "low"})
        self.assertEqual(a["as3"], {"never_run": "low", "use_not_checked": "low"})

    def test_highest_priority_first(self):
        out = full()
        self.assertEqual(out["audiences"][0]["findings"][0]["priority"], "high")
        self.assertEqual(out["summary"]["duplicates"], 1)

    def test_context_error_stops_and_url_is_redacted(self):
        code, out = run("--external", f("denied.json"))
        self.assertEqual(code, 1)
        self.assertIn("ACCESS_DENIED", out)
        self.assertNotIn("token=", out)

    def test_size_from_eql_reads_the_count_column_only(self):
        out = full("--size", f"ext3={f('eql_size.json')}")
        a = audience(out, "ext3")
        self.assertEqual(a["size"], 800)  # 700 + 100, not the second column
        self.assertIn("too_small", kinds(a))

    def test_size_must_be_a_number_or_a_json_path(self):
        code, _ = run("--external", f("external.json"), "--size", "ext1=lots")
        self.assertEqual(code, 1)
        code, out = run("--external", f("external.json"), "--size", "ext1=nothere.json")
        self.assertEqual(code, 1)
        self.assertIn("can't read", out)

    def test_needs_an_input(self):
        code, out = run("--today", "2026-11-04")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
