"""Tests for engagement-media-cleanup's media_library_audit.py. The fixtures are synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins/loomi-engagement/skills/engagement-media-cleanup"
SCRIPT = SKILL / "scripts/media_library_audit.py"
FIX = ROOT / "tests/fixtures/engagement/engagement-media-cleanup"

FILES = ["files_root.json", "files_folder.json"]
ASSETS = ["email_block=blocks_list.json", "email_block=blocks_details.json", "snippet=snippet_detail.json",
          "sms_asset=sms_assets_list.json", "sms_asset=sms_asset_detail.json", "email_asset=email_asset_detail.json",
          "app_inbox_design=app_inbox_list.json"]
USAGE = ["email=email_live.json", "email=email_draft.json", "scenario=scenario_live.json", "sms=sms_list.json",
         "banner=banner_live.json", "in_app_message=in_app_inactive.json"]


def run(*args):
    """Run the script by its full path from a fresh working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=tmp, capture_output=True,
                           text=True, encoding="utf-8", timeout=60)
        assert not any(Path(tmp).iterdir()), "the script wrote to the working folder"
    return r


def inputs(files=FILES, assets=ASSETS, usage=USAGE):
    args = []
    for f in files:
        args += ["--files", FIX / f]
    for pair in assets:
        kind, name = pair.split("=", 1)
        args += ["--asset", f"{kind}={FIX / name}"]
    for pair in usage:
        kind, name = pair.split("=", 1)
        args += ["--usage", f"{kind}={FIX / name}"]
    return args + ["--today", "2026-11-04"]


def audit(*extra, **kw):
    r = run(*inputs(**kw), *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout), r.stdout


def item(rows, name):
    return next(r for r in rows if r["name"] == name)


def codes(r):
    return [f["code"] for f in r["findings"]]


class MediaLibraryAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out, cls.raw = audit()

    def test_states_through_blocks_and_snippets(self):
        files = self.out["files"]
        self.assertEqual(item(files, "logo.png")["state"], "live")  # inside a block a live scenario uses
        self.assertEqual(item(files, "promo-draft.png")["state"], "draft_only")
        self.assertEqual(item(files, "template-only.png")["state"], "template_only")
        self.assertEqual(item(files, "new-promo.jpg")["state"], "unused")
        assets = self.out["assets"]
        self.assertEqual(item(assets, "Footer logo block")["state"], "live")
        self.assertEqual(item(assets, "Unsubscribe line")["state"], "live")
        self.assertEqual(item(assets, "Test block")["state"], "unused")

    def test_templates_not_traceable_but_sms_copy_found(self):
        assets = self.out["assets"]
        self.assertEqual(item(assets, "Shipping update")["state"], "live")
        self.assertEqual(item(assets, "Shipping update")["used_by"][0]["how"], "copied text")
        self.assertEqual(item(assets, "Spring sale 2023")["state"], "not_traceable")
        self.assertEqual(item(assets, "Inbox promo")["state"], "not_traceable")
        self.assertEqual(item(assets, "Newsletter template")["action"], "review")

    def test_live_problems_are_fixes(self):
        hero = item(self.out["files"], "hero-banner.png")
        self.assertEqual(hero["action"], "fix")
        self.assertEqual(codes(hero), ["huge_image", "missing_alt", "oversized_dimensions"])
        archived = item(self.out["files"], "archived-banner.jpg")
        self.assertEqual((codes(archived), archived["priority"]), (["archived_in_use"], "high"))

    def test_duplicates(self):
        copy = item(self.out["files"], "logo.d7e9962cbacf5f0d2076.png")
        self.assertIn("duplicate", codes(copy))
        self.assertIn("same name and size", copy["findings"][0]["detail"] + copy["findings"][1]["detail"])
        final = item(self.out["files"], "hero-banner-final.png")
        self.assertIn("duplicate", codes(final))
        self.assertIn("insecure_url", codes(final))
        self.assertNotIn("duplicate", codes(item(self.out["files"], "logo.png")))
        self.assertIn("duplicate_name", codes(item(self.out["assets"], "Footer logo block (1)")))

    def test_delete_and_review_lists(self):
        deletes = sorted(d["name"] for d in self.out["delete_candidates"])
        self.assertEqual(deletes, ["Footer logo block (1)", "Test block", "hero-banner-final.png",
                                   "logo.d7e9962cbacf5f0d2076.png", "old-test-image.png"])
        reviews = {d["name"] for d in self.out["review"]}
        self.assertIn("new-promo.jpg", reviews)  # unused but recent
        self.assertIn("template-only.png", reviews)

    def test_content_findings(self):
        rows = {r["name"]: r for r in self.out["content_findings"]}
        email = rows["Black Friday launch"]
        self.assertEqual(codes(email), ["insecure_image", "missing_alt"])
        self.assertIn("1 of 2 images", email["findings"][1]["detail"])  # pixel skipped, design counted once
        self.assertEqual(codes(rows["Exit popup"]), ["insecure_image"])
        self.assertNotIn("Spring preview", rows)

    def test_privacy(self):
        for secret in ("Pat Example", "FAKE", "token=", "Bearer", "shipped and is on its way"):
            self.assertNotIn(secret, self.raw)

    def test_missing_usage_kind_makes_unused_unverified(self):
        out, _ = audit(usage=[u for u in USAGE if not u.startswith("banner=")])
        self.assertEqual(item(out["files"], "new-promo.jpg")["state"], "unused_unverified")
        self.assertTrue(any("banner" in n for n in out["not_checked"]))
        self.assertEqual(out["delete_candidates"], [])

    def test_denied_kind_and_list_only_blocks(self):
        out, _ = audit("--denied", "in_app_message", assets=[a for a in ASSETS if "blocks_details" not in a])
        self.assertEqual(item(out["files"], "old-test-image.png")["state"], "unused_unverified")
        self.assertEqual(item(out["files"], "logo.png")["state"], "unused_unverified")
        text = " ".join(out["not_checked"])
        self.assertIn("in_app_message", text)
        self.assertIn("list only (no content)", text)

    def test_access_error_stops_but_not_found_skips(self):
        r = run(*inputs(), "--usage", f"email={FIX / 'denied.json'}")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--denied", json.loads(r.stdout)["error"])
        out, _ = audit("--asset", f"snippet={FIX / 'not_found.json'}")
        self.assertEqual(out["summary"]["assets"], 8)

    def test_unbrowsed_folder_reported(self):
        out, _ = audit(files=["files_root.json"])
        self.assertTrue(any("dir-0001" in n for n in out["not_checked"]))
        self.assertFalse(any("dir-0001" in n for n in self.out["not_checked"]))

    def test_deterministic_and_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "audit.json"
            r = subprocess.run([sys.executable, str(SCRIPT), *map(str, inputs()), "--out", str(target)], cwd=tmp,
                               capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(target.read_text(encoding="utf-8"), self.raw)

    def test_bad_kind_fails(self):
        r = run("--files", FIX / "files_root.json", "--usage", f"webhook={FIX / 'email_live.json'}")
        self.assertEqual(r.returncode, 1)

    def test_every_rule_has_a_note(self):
        rules = json.loads((SKILL / "references/rules.json").read_text(encoding="utf-8"))
        missing = [k for k in rules if k not in ("about", "notes") and k not in rules["notes"]]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
