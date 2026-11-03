"""Tests for message_checks.py, the static message checks shared by campaign-qa, scenario-qa and
engagement-send-preflight. The fixtures are synthetic campaign, SMS and scenario detail results."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/campaign-qa"
SCRIPT = SKILL / "scripts/message_checks.py"
FX = ROOT / "tests/fixtures/engagement/message_checks"


def run(*args):
    # Run from an empty folder, so a script that wrote next to itself or to the working folder would show.
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                           encoding="utf-8", cwd=tmp)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r.returncode, json.loads(r.stdout)


def checks(result, message):
    m = next(m for m in result["messages"] if m["message"] == message)
    return {(f["severity"], f["check"]) for f in m["findings"]}


class MessageChecksTest(unittest.TestCase):
    def test_clean_email_passes(self):
        code, out = run(FX / "email_clean.json", "--regions", "US,CA")
        self.assertEqual(code, 0)
        self.assertEqual(out["counts"], {"blocker": 0, "warning": 0, "nitpick": 0}, out["messages"][0]["findings"])
        self.assertEqual(out["verdict_before_link_checks"], "GO")
        # System links are left for render time; real links are listed for loading, primary first.
        self.assertIn("{{ email.unsubscribe }}", out["links_needing_render"])
        self.assertTrue(out["links_to_load"][0]["primary"])

    def test_broken_email_variant(self):
        _, out = run(FX / "email_broken.json", "--regions", "US,CA")
        found = checks(out, "Broken promo / Variant A")
        for expected in [("blocker", "unsubscribe_missing"), ("blocker", "placeholder"), ("blocker", "jinja_syntax"),
                         ("blocker", "event_without_trigger"), ("blocker", "consent_missing"), ("blocker", "near_miss_host"),
                         ("blocker", "missing_scheme"), ("blocker", "casl_contact"), ("warning", "preheader_missing"),
                         ("warning", "address_not_found"), ("warning", "alt_missing"), ("warning", "image_only"),
                         ("warning", "spam_risk"), ("warning", "no_fallback"), ("warning", "default_without_true"),
                         ("warning", "unguarded_aggregate"), ("warning", "no_tls"), ("warning", "placeholder_words"),
                         ("warning", "placeholder_link"), ("nitpick", "view_online_missing"), ("nitpick", "frequency_unlimited")]:
            self.assertIn(expected, found)
        self.assertEqual(out["verdict_before_link_checks"], "NO-GO")
        spam = next(m for m in out["messages"] if m["variant"] == "Variant A")["stats"]["spam"]
        self.assertEqual(spam["level"], "high")
        self.assertTrue(any("points to evil.test" in r for r in spam["reasons"]))

    def test_non_web_links_are_never_loaded(self):
        _, out = run(FX / "email_broken.json")
        self.assertIn(("warning", "non_web_link"), checks(out, "Broken promo / Variant A"))
        self.assertTrue(all(l["url"].startswith(("http://", "https://")) for l in out["links_to_load"]))

    def test_emails_masked_in_evidence(self):
        _, out = run(FX / "email_broken.json")
        evidence = [f.get("evidence", "") for m in out["messages"] for f in m["findings"]]
        self.assertIn("http://brxcdn.com/a?e=<email>", evidence)
        self.assertFalse(any("jane@" in e for e in evidence))

    def test_split_checks(self):
        _, out = run(FX / "email_split.json")
        self.assertEqual({(f["severity"], f["check"]) for f in out["campaign_findings"]},
                         {("blocker", "split_total"), ("warning", "split_identical")})
        self.assertEqual(out["counts"]["blocker"], 1)
        self.assertEqual(out["verdict_before_link_checks"], "NO-GO")

    def test_subject_preheader_size_links_sender(self):
        links = "".join(f'<a href="https://www.acme-outdoors.test/p/{i}">Product {i}</a> ' for i in range(60))
        html = ('<p>Acme Outdoors, 1 Harbour Street, Sampletown, CA 94105. <a href="{{ email.unsubscribe }}">Unsubscribe</a> '
                '<a href="{{ email.view }}">View in browser</a></p><p>' + "Ordinary copy about jackets and boots. " * 8
                + "</p>" + links + "<!-- " + "x" * 110 * 1024 + " -->")
        data = {"_id": "1", "name": "Edge", "schedule": {"type": "now"}, "consent_category": "newsletter",
                "frequency_policy": "Default", "design": {"type": "beefree", "data": {
                    "jinja_html": html, "subject": "", "preheader": "p" * 140, "sender_name": "", "sender_email": ""}}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edge.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            _, out = run(path)
            found = checks(out, "Edge")
            for expected in [("blocker", "subject_missing"), ("nitpick", "preheader_length"), ("warning", "size"),
                             ("nitpick", "many_links"), ("warning", "sender_missing")]:
                self.assertIn(expected, found)
            self.assertEqual(len(out["links_to_load"]) + len(out["links_over_cap"]), 60)
            data["design"]["data"]["subject"] = "S" * 80
            path.write_text(json.dumps(data), encoding="utf-8")
            _, out = run(path)
            self.assertIn(("nitpick", "subject_length"), checks(out, "Edge"))

    def test_sms_and_push_edges(self):
        _, out = run(FX / "sms_edge.json")
        self.assertIn(("blocker", "sms_empty"), checks(out, "Edge SMS"))
        fr = checks(out, "Edge SMS / fr")
        self.assertIn(("warning", "restricted_content"), fr)
        self.assertNotIn(("nitpick", "sms_encoding"), fr)  # emoji force UCS-2 for real, not just curly quotes
        _, out = run(FX / "push_edge.json")
        self.assertEqual(checks(out, "Long push"), {("nitpick", "push_length")})

    def test_bad_input(self):
        code, out = run(FX / "missing.json")
        self.assertEqual(code, 1)
        self.assertIn("can't read it", out["error"])
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(SCRIPT), str(FX / "scenario.json"), "--node-ids", "abc"],
                               capture_output=True, text=True, encoding="utf-8", cwd=tmp)
        self.assertEqual(r.returncode, 2)
        self.assertIn("comma-separated numbers", r.stderr)

    def test_emoji_output_on_a_cp1252_console(self):
        import os
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        r = subprocess.run([sys.executable, str(SCRIPT), str(FX / "sms_edge.json")], capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_each_variant_checked_separately(self):
        _, out = run(FX / "email_broken.json")
        b = checks(out, "Broken promo / Variant B")
        self.assertIn(("nitpick", "preheader_repeats_subject"), b)
        self.assertNotIn(("blocker", "unsubscribe_missing"), b)

    def test_canada_check_only_with_region(self):
        _, out = run(FX / "email_broken.json", "--regions", "US")
        self.assertNotIn(("blocker", "casl_contact"), checks(out, "Broken promo / Variant A"))

    def test_sms_campaign(self):
        _, out = run(FX / "sms_campaign.json", "--regions", "US,US-TX")
        es = checks(out, "Weekend SMS / es")
        for expected in [("blocker", "sms_opt_out"), ("blocker", "sms_brand"), ("blocker", "placeholder"),
                         ("blocker", "sms_quiet_hours"), ("warning", "sms_length"), ("warning", "public_shortener"),
                         ("nitpick", "sms_help"), ("nitpick", "sms_encoding")]:
            self.assertIn(expected, es)
        en = checks(out, "Weekend SMS")
        self.assertEqual(en, {("blocker", "sms_quiet_hours")})

    def test_sms_brand_is_a_warning_outside_texas_and_canada(self):
        _, out = run(FX / "sms_campaign.json", "--regions", "US")
        self.assertIn(("warning", "sms_brand"), checks(out, "Weekend SMS / es"))

    def test_sms_brand_name_given(self):
        _, out = run(FX / "sms_campaign_clean.json", "--brand", "Acme Outdoors")
        self.assertEqual(out["counts"]["blocker"] + out["counts"]["warning"] + out["counts"]["nitpick"], 0)
        _, out = run(FX / "sms_campaign_clean.json", "--brand", "Other Brand")
        self.assertIn(("warning", "sms_brand"), checks(out, "Weekend SMS"))

    def test_scenario_nodes(self):
        _, out = run(FX / "scenario.json")
        self.assertEqual([m["message"] for m in out["messages"]], ["Cart email", "Cart SMS", "Cart push"])
        # event.* is fine in a scenario step: the trigger supplies it.
        self.assertNotIn(("blocker", "event_without_trigger"), checks(out, "Cart email"))
        self.assertEqual(checks(out, "Cart SMS"), {("nitpick", "sms_help"), ("nitpick", "frequency_unlimited")})
        self.assertEqual(checks(out, "Cart push"), {("blocker", "push_empty"), ("blocker", "push_link"),
                                                    ("blocker", "placeholder"), ("warning", "consent_missing")})
        self.assertEqual(out["not_checked"], [{"id": 6, "name": "Cart WhatsApp", "type": "send-whatsapp-action",
                                               "source": "scenario", "parent_id": "000000000000000000000004"}])

    def test_node_ids_and_several_inputs(self):
        _, out = run(FX / "scenario.json", FX / "sms_campaign_clean.json", "--node-ids", "4")
        self.assertEqual([m["message"] for m in out["messages"]], ["Cart SMS", "Weekend SMS"])

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "findings.json"
            _, out = run(FX / "email_clean.json", "--out", out_path)
            self.assertEqual(json.loads(out_path.read_text(encoding="utf-8")), out)

    def test_errors(self):
        for name, text in [("email_stripped.json", "include_design=true"), ("error.json", "ACCESS_DENIED"),
                           ("list.json", "list result")]:
            code, out = run(FX / name)
            self.assertEqual(code, 1)
            self.assertFalse(out["ok"])
            self.assertIn(text, out["error"])


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        keys = set(rules) - {"about", "notes"}
        self.assertEqual(keys, set(rules["notes"]))

    def test_every_copy_matches(self):
        # The validator keeps the script copies identical; their rules and check catalog must match too.
        copies = sorted(ROOT.glob("plugins/*/skills/*/scripts/message_checks.py"))
        self.assertGreater(len(copies), 1)
        for name in ("rules.json", "message-checks.md"):
            canonical = (SKILL / "references" / name).read_bytes()
            for script in copies:
                self.assertEqual((script.parent.parent / "references" / name).read_bytes(), canonical, script)


    def test_word_lists_shared_with_weblayer_qa(self):
        # engagement-weblayer-qa has its own script but must judge placeholder links the same way.
        ours = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        web = json.loads((ROOT / "plugins/loomi-engagement/skills/engagement-weblayer-qa/references/rules.json")
                         .read_text(encoding="utf-8"))
        for key in ("placeholder_hosts", "placeholder_words"):
            self.assertEqual(ours[key], web[key], key)


if __name__ == "__main__":
    unittest.main()
