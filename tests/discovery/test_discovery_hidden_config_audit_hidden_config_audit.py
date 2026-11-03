"""Tests for discovery-hidden-config-audit's hidden_config_audit.py. The fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-hidden-config-audit"
SCRIPT = SKILL / "scripts/hidden_config_audit.py"
FIX = ROOT / "tests/fixtures/discovery/hidden_config"


def run(*args):
    """Run the script by its full path from a fresh working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp, capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def full():
    r = run("--audiences", FIX / "audiences.json",
            "--audience-rules", f"100={FIX / 'rules_100.json'}", "--audience-rules", f"102={FIX / 'rules_102.json'}",
            "--audience-rules", f"113={FIX / 'rules_113.json'}", "--api-params", FIX / "api_params.json",
            "--rules", FIX / "rules_all.json", "--today", "2026-11-03")
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def finding(out, area, fid, issue_start):
    return next((f for f in out["findings"] if f["area"] == area and f["id"] == fid and f["issue"].startswith(issue_start)), None)


class AudienceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = full()

    def test_cant_match_with_live_rules_is_fix_now(self):
        f = finding(self.out, "audience", 102, "Audience can't match")
        self.assertEqual(f["priority"], "high")
        self.assertIn("trailing space", f["evidence"])
        self.assertIn("9003", f["evidence"])

    def test_contradiction_is_fix_now(self):
        f = finding(self.out, "audience", 112, "Audience can't match")
        self.assertEqual(f["priority"], "high")
        self.assertIn("both IS and IS NOT", f["evidence"])

    def test_identical_conditions_both_used(self):
        f = finding(self.out, "audience", 100, "Audiences with identical conditions")
        self.assertEqual(f["priority"], "high")
        self.assertIn("101", f["evidence"])

    def test_unused_audiences(self):
        self.assertEqual(finding(self.out, "audience", 103, "Unused audience that can't match")["priority"], "low")
        self.assertEqual(finding(self.out, "audience", 106, "Unused test audience")["priority"], "low")
        self.assertEqual(finding(self.out, "audience", 107, "New audience")["priority"], "medium")
        # Complementary IS / IS NOT audiences are fine as a pair; here they're only flagged for being unused.
        self.assertIsNone(finding(self.out, "audience", 110, "Overlaps"))

    def test_only_disabled_or_expired_rules(self):
        self.assertEqual(finding(self.out, "audience", 113, "Audience only drives")["priority"], "low")

    def test_risky_values(self):
        self.assertIn("is short", finding(self.out, "audience", 104, "Condition probably")["evidence"])
        self.assertIn("starts with &", finding(self.out, "audience", 105, "Condition probably")["evidence"])
        self.assertIn("accented", finding(self.out, "audience", 114, "Condition probably")["evidence"])

    def test_overlap(self):
        f = finding(self.out, "audience", 108, "Overlaps another audience")
        self.assertEqual(f["priority"], "medium")
        self.assertIn("109", f["evidence"])

    def test_protected_is_never_cleaned_up(self):
        self.assertIn(105, [p["id"] for p in self.out["protected"] if p["area"] == "audience"])
        self.assertFalse(any(f["id"] == 105 and f["priority"] == "low" for f in self.out["findings"]))

    def test_personalised_map_and_coverage(self):
        rows = {r["rule_id"]: r for r in self.out["personalised_rules"]}
        self.assertEqual(rows[9001]["audience"], "Top tier")
        self.assertEqual(rows[9003]["queries"], ["spring dresses"])
        self.assertEqual(self.out["audiences_not_fully_accounted"],
                         [{"audience_id": 113, "audience": "Style formal", "rules_affected": 3, "found_in_lists": 2}])
        self.assertIn(104, [a["audience_id"] for a in self.out["audience_rules_not_fetched"]])
        self.assertEqual(self.out["engagement_dependencies"], [{"engagement_segment": "Style Preference", "audiences": [113]}])

    def test_never_repeats_editors(self):
        self.assertNotIn("editor@example.test", json.dumps(self.out))


class OverrideTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = full()

    def test_fix_now(self):
        self.assertEqual(finding(self.out, "api_param", 502, "Overrides br_diagnostics")["priority"], "high")
        self.assertEqual(finding(self.out, "api_param", 503, "Expired override")["priority"], "high")
        dup = finding(self.out, "api_param", 501, "sort is overridden by more than one")
        self.assertEqual((dup["priority"], dup["evidence"]), ("high", "overrides 501, 507"))

    def test_review_with_conflict_context(self):
        f = finding(self.out, "api_param", 501, "Overrides sort")
        self.assertEqual(f["priority"], "medium")
        self.assertIn("2 enabled ranking rule(s)", f["evidence"])
        self.assertIn("every search and category request", f["evidence"])
        self.assertIn("queries 'sale'", finding(self.out, "api_param", 506, "Overrides rows")["evidence"])

    def test_unreadable_old_and_unnamed(self):
        self.assertEqual(finding(self.out, "api_param", 505, "Couldn't read")["priority"], "medium")
        self.assertEqual(finding(self.out, "api_param", 504, "Old disabled override")["priority"], "low")
        self.assertEqual(finding(self.out, "api_param", 508, "Unnamed old override")["priority"], "medium")

    def test_summary(self):
        s = self.out["summary"]
        self.assertEqual((s["audiences"], s["api_param_overrides"], s["api_param_overrides_enabled"]), (15, 9, 8))
        self.assertEqual(s["high"] + s["low"] + s["medium"], len(self.out["findings"]))


class InputTest(unittest.TestCase):
    def test_overrides_only_and_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "audit.json"
            r = run("--api-params", FIX / "api_params.json", "--today", "2026-11-03", "--out", out)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), json.loads(r.stdout))
        # Without --rules there's no rule-count context.
        self.assertNotIn("ranking rule(s)", r.stdout)

    def test_errors(self):
        cases = [(("--today", "2026-11-03"), "Give --audiences"),
                 (("--audiences", FIX / "error.json", "--today", "2026-11-03"), "ACCESS_DENIED"),
                 (("--audiences", FIX / "missing.json", "--today", "2026-11-03"), "can't read it")]
        for args, text in cases:
            r = run(*args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn(text, r.stdout, args)
        # Argument mistakes are argparse errors: exit 2, message on stderr, no traceback.
        for args, text in [(("--audiences", FIX / "audiences.json", "--audience-rules", "abc"), "<audience id>=<file>"),
                           (("--audiences", FIX / "audiences.json", "--audience-rules", f"x={FIX / 'rules_100.json'}"),
                            "numeric audience id"),
                           (("--audiences", FIX / "audiences.json", "--today", "yesterday"), "YYYY-MM-DD")]:
            r = run(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn(text, r.stderr, args)
            self.assertNotIn("Traceback", r.stderr)

    def test_account_list_errors_are_not_repeated(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "params.json"
            bad.write_text(json.dumps({"success": False, "error": "Unknown account 'acme'. Accounts you can access: "
                                       "alpha_store, beta_store, gamma_store, delta_store"}), encoding="utf-8")
            r = run("--api-params", bad, "--today", "2026-11-03")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("beta_store", r.stdout)
        self.assertIn("Ask the user to check the account name", r.stdout)

    def test_malformed_records_name_the_file_and_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "aud.json"
            bad.write_text(json.dumps({"success": True, "data": [{"id": 1, "dimensionList": "oops"}]}), encoding="utf-8")
            r = run("--audiences", bad, "--today", "2026-11-03")
        self.assertEqual(r.returncode, 1)
        self.assertIn("dimensionList isn't a list", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_today_defaults_to_utc_today(self):
        from datetime import datetime, timezone
        r = run("--api-params", FIX / "api_params.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["today"], datetime.now(timezone.utc).date().isoformat())

    def test_audience_file_splits_on_the_first_equals(self):
        with tempfile.TemporaryDirectory() as tmp:
            odd = Path(tmp) / "rules=100.json"  # a file name with "=" in it
            odd.write_text((FIX / "rules_100.json").read_text(encoding="utf-8"), encoding="utf-8")
            r = run("--audiences", FIX / "audiences.json", "--audience-rules", f"100={odd}", "--today", "2026-11-03")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(9001, [x["rule_id"] for x in json.loads(r.stdout)["personalised_rules"]])

    def test_secret_url_parameters_are_redacted(self):
        aud = json.loads((FIX / "audiences.json").read_text(encoding="utf-8"))
        aud["data"].append({"id": 900, "audienceName": "Email link", "rulesAffected": 1, "createdAt": 1700000000000,
                            "dimensionList": [{"internalName": "url", "externalName": "URL", "type": "discovery",
                                               "dimensionValueList": [{"internalValue": "?email=shopper@example.test&ref=ab",
                                                                       "matchtype": {"internalName": "CONTAIN_MATCH"}},
                                                                      {"internalValue": "&token=abc123 ",
                                                                       "matchtype": {"internalName": "CONTAIN_MATCH"}}]}]})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "aud.json"
            path.write_text(json.dumps(aud), encoding="utf-8")
            r = run("--audiences", path, "--today", "2026-11-03")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("shopper@example.test", r.stdout)
        self.assertNotIn("abc123", r.stdout)
        self.assertIn("token=[redacted]", r.stdout)


class RulesTest(unittest.TestCase):
    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
