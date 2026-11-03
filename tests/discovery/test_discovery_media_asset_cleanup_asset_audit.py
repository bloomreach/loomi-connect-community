"""Tests for discovery-media-asset-cleanup's asset_audit.py, on synthetic media assets and media rules."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-discovery/skills/discovery-media-asset-cleanup"
SCRIPT = SKILL / "scripts/asset_audit.py"
FX = ROOT / "tests/fixtures/discovery/media_assets"
NOW = "2026-11-04T00:00:00Z"


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp, capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r.returncode, json.loads(r.stdout) if r.stdout else None, r.stderr


def full(*extra):
    code, out, err = run("--assets", FX / "assets.json", "--rules", FX / "rules_site.json", "--details", FX / "details.json",
                         "--multi-slot", FX / "multi_slot.json", "--now", NOW, *extra)
    assert code == 0, err
    return out


def checks(entry):
    return {(f["severity"], f["check"]) for f in entry["findings"]}


class AssetAuditTest(unittest.TestCase):
    def setUp(self):
        self.out = full()
        self.assets = {a["asset_id"]: a for a in self.out["assets"]}
        self.rules = {r["rule_id"]: r for r in self.out["rules"]}

    def test_usage(self):
        usage = {i: a["usage"] for i, a in self.assets.items()}
        self.assertEqual(usage, {1001: "live", 1002: "live", 1003: "unused_unverified", 1004: "inactive_only",
                                 1005: "unused_unverified", 1006: "live", 1007: "unused_unverified"})
        self.assertNotIn(1008, self.assets)  # deleted assets are left out
        self.assertEqual(self.out["not_checked"], {"rules_without_detail": [2004], "multi_slot_rules_without_detail": [2005]})

    def test_unused_is_verified_when_every_rule_was_fetched(self):
        code, out, _ = run("--assets", FX / "assets.json", "--details", FX / "details.json", "--now", NOW)
        self.assertEqual(code, 0)
        self.assertEqual({a["asset_id"]: a["usage"] for a in out["assets"]}[1003], "unused")

    def test_asset_content_checks(self):
        self.assertEqual(checks(self.assets[1002]), {("medium", "no_tls"), ("low", "hotlinked_image")})
        self.assertIn(("medium", "not_a_url"), checks(self.assets[1003]))
        self.assertIn(("low", "stale"), checks(self.assets[1003]))
        # The placeholder link is high in principle, but the asset isn't live, so it's medium.
        self.assertTrue({("medium", "missing_scheme"), ("medium", "placeholder_link"), ("low", "inactive_only")}
                        <= checks(self.assets[1004]))
        self.assertIn(("medium", "placeholder_link"), checks(self.assets[1005]))
        self.assertIn(("medium", "unreadable"), checks(self.assets[1007]))
        self.assertIn(("low", "hotspot_alt"), checks(self.assets[1001]))

    def test_disabled_and_duplicate_assets(self):
        self.assertTrue({("medium", "disabled_but_used"), ("low", "asset_disabled"), ("low", "duplicate_image")}
                        <= checks(self.assets[1006]))
        self.assertIn(("low", "duplicate_image"), checks(self.assets[1001]))

    def test_rule_placement_checks(self):
        self.assertEqual(checks(self.rules[2001]), {("high", "missing_asset"), ("high", "overlapping_slots"),
                                                     ("medium", "slot_out_of_range"), ("low", "variants_not_checked")})
        self.assertEqual(checks(self.rules[2002]), {("medium", "empty_placement")})
        self.assertEqual(checks(self.rules[2003]), {("medium", "multi_slot_shape")})
        self.assertFalse(self.rules[2003]["live"])

    def test_priority_order_and_links(self):
        order = [a["priority"] for a in self.out["assets"]]
        self.assertEqual(order, sorted(order, key={"high": 0, "medium": 1, "low": 2}.get))
        urls = [l["url"] for l in self.out["links_to_load"]]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertTrue(all(u.startswith(("http://", "https://")) for u in urls))
        self.assertNotIn("https://example.com/a.png", urls)  # placeholders aren't worth loading

    def test_never_copies_editor_names(self):
        text = json.dumps(self.out)
        self.assertNotIn("editor@acme.test", text)
        self.assertNotIn("lastModifiedBy", text)

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.json"
            out = full("--out", path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), out)

    def test_errors(self):
        code, out, _ = run("--assets", FX / "denied.json")
        self.assertEqual(code, 1)
        self.assertIn("ACCESS_DENIED", out["error"])
        code, out, _ = run("--assets", FX / "missing.json")
        self.assertEqual(code, 1)
        self.assertIn("can't read it", out["error"])
        code, out, _ = run("--assets", FX / "assets.json", "--now", "soon")
        self.assertEqual(code, 1)
        self.assertIn("--now", out["error"])

    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rules) - {"about", "notes"}, set(rules["notes"]))


if __name__ == "__main__":
    unittest.main()
