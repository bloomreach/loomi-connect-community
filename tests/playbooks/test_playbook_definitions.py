"""Checks every playbook in plugins/loomi-playbooks against the skills it chains: the stages name skills that
exist, a stage marked as writing runs a write skill (and only then), the playbook is a write skill exactly when a
stage writes, every rules key has a note, and each playbook ships the same handoff.py."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAYBOOKS = sorted((ROOT / "plugins/loomi-playbooks/skills").glob("playbook-*/"))
CANONICAL = ROOT / "plugins/loomi-playbooks/skills/playbook-test-and-learn/scripts/handoff.py"
PRODUCTS = {"discovery", "engagement", "both"}


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    return dict(re.findall(r"^\s*(name|access|products|version):\s*\"?([^\"\n]+)\"?", text.split("\n---", 1)[0], re.M))


SKILLS = {p.parent.name: frontmatter(p) for p in ROOT.glob("plugins/*/skills/*/SKILL.md")}


class PlaybookDefinitionsTest(unittest.TestCase):
    def test_there_are_playbooks(self):
        self.assertTrue(PLAYBOOKS)

    def test_each_playbook(self):
        for pb in PLAYBOOKS:
            with self.subTest(playbook=pb.name):
                rules = json.loads((pb / "references/rules.json").read_text(encoding="utf-8"))
                keys = set(rules) - {"about", "notes"}
                self.assertTrue(rules.get("about"))
                self.assertEqual(keys - set(rules["notes"]), set(), "every rules key needs a note")
                self.assertEqual((pb / "scripts/handoff.py").read_bytes(), CANONICAL.read_bytes(),
                                 "every playbook ships the same handoff.py")
                name = pb.name.removeprefix("playbook-")
                self.assertIn(name, rules["playbooks"], "the playbook's key is its skill name without 'playbook-'")
                self.assertEqual(set(rules["playbooks"]), {name}, "one playbook per skill")
                spec = rules["playbooks"][name]
                self.assertIn(spec["product"], PRODUCTS)
                self.assertTrue(spec["title"])
                stages = spec["stages"]
                names = [s["name"] for s in stages]
                self.assertEqual(len(names), len(set(names)))
                self.assertGreaterEqual(len(stages), 2)
                outcomes = set()
                for i, s in enumerate(stages):
                    self.assertIn(s["skill"], SKILLS, f"stage {s['name']} names a skill that doesn't exist")
                    self.assertNotEqual(s["skill"], pb.name)
                    stage_writes = SKILLS[s["skill"]].get("access") == "writes"
                    self.assertEqual(s["writes"], stage_writes,
                                     f"stage {s['name']}: writes must match {s['skill']}'s access")
                    self.assertTrue(s["do"].strip())
                    if "product" in s:
                        self.assertIn(s["product"], {"discovery", "engagement"})
                        self.assertEqual(spec["product"], "both", "only a playbook on both products marks stage products")
                    self.assertTrue(s["outcomes"])
                    outcomes |= set(s["outcomes"])
                    nb = s.get("not_before")
                    if nb:
                        self.assertIn(nb["after_stage"], names[:i], "not_before must follow an earlier stage")
                        self.assertIsInstance(rules.get(nb["days"]), int, f"{nb['days']} must be a number in rules.json")
                    for entry in s.get("skip_when", []):
                        self.assertTrue(entry["reason"])
                        for cond in entry.get("all", [entry]):
                            self.assertIn(cond["stage"], names[:i], "skip_when must look at an earlier stage")
                            other = next(x for x in stages if x["name"] == cond["stage"])
                            self.assertTrue(cond.get("skipped") is True or cond.get("outcomes"),
                                            "skip_when needs outcomes or skipped")
                            self.assertLessEqual(set(cond.get("outcomes", [])), set(other["outcomes"]))
                self.assertLessEqual(set(rules.get("wait_outcomes", [])), outcomes)
                writes = any(s["writes"] for s in stages)
                fm = frontmatter(pb / "SKILL.md")
                self.assertEqual(fm.get("access"), "writes" if writes else "read-only")
                yaml = (pb / "agents/openai.yaml").read_text(encoding="utf-8")
                self.assertIn(f"allow_implicit_invocation: {'false' if writes else 'true'}", yaml)
                body = (pb / "SKILL.md").read_text(encoding="utf-8")
                for s in stages:
                    self.assertIn(f"`{s['skill']}`", body, f"SKILL.md should name the stage skill {s['skill']}")
                if writes:
                    self.assertIn("## Safety", body.split("## What this does")[0], "write playbooks start with Safety")


if __name__ == "__main__":
    unittest.main()
