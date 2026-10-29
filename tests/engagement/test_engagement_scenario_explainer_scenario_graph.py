import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plugins/loomi-engagement/skills/engagement-scenario-explainer/scripts/scenario_graph.py"
FIXTURES = ROOT / "tests/fixtures/engagement"


def run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              cwd=tmp, capture_output=True, text=True)


class ScenarioGraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = run(FIXTURES / "scenario_splits.json")
        assert r.returncode == 0, r.stderr
        cls.out = r.stdout

    def test_help(self):
        self.assertEqual(run("--help").returncode, 0)

    def test_ab_split_branches_by_variant_id(self):
        self.assertIn("(Control) [7] limit", self.out)  # output 4 = variant id 4, not position 3
        self.assertIn("(Free ship) [4]", self.out)

    def test_contextual_split_is_id_plus_one(self):
        self.assertIn("(Ctx A) [11]", self.out)
        self.assertIn("(Ctx B) [12]", self.out)

    def test_limit_outputs(self):
        self.assertIn("(within limit) [8]", self.out)
        self.assertIn("(over limit) [9]", self.out)

    def test_warnings(self):
        warnings = self.out.split("## Warnings", 1)[1]
        self.assertIn("output 3, but no variant has that id", warnings)
        self.assertIn("add up to 90%", warnings)
        self.assertIn("Dangling wait [5]", warnings)
        self.assertNotIn("Dangling wait [9]", warnings)
        self.assertNotIn("Contextual\": variant percentages", warnings)

    def test_condition_and_limit_with_no_branches_lead_nowhere(self):
        scenario = {"success": True, "data": {"name": "Synthetic dead ends", "nodes": [
            {"id": "1", "type": "on-event-trigger", "name": "Signed up", "event": {"type": "registration", "filter": []}},
            {"id": "2", "type": "condition", "name": "Has email", "customer_filter": {"filters": [], "formula": ""}},
            {"id": "3", "type": "limit", "name": "Cap", "steps": [{"group": "", "id": "b" * 24, "limit": "1"}]},
            {"id": "4", "type": "limit", "name": "Cap ok", "steps": [{"group": "", "id": "c" * 24, "limit": "2"}]},
            {"id": "5", "type": "send-email-action", "name": "Mail", "template_id": None}],
            "connections": [
                {"source": {"node_id": "1", "connector_index": 0}, "destination": {"node_id": "2", "connector_index": 0}},
                {"source": {"node_id": "1", "connector_index": 0}, "destination": {"node_id": "3", "connector_index": 0}},
                {"source": {"node_id": "1", "connector_index": 0}, "destination": {"node_id": "4", "connector_index": 0}},
                {"source": {"node_id": "4", "connector_index": 1}, "destination": {"node_id": "5", "connector_index": 0}}]}}
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "dead_ends.json"
            p.write_text(json.dumps(scenario))
            r = run(p)
        self.assertEqual(r.returncode, 0, r.stderr)
        warnings = r.stdout.split("## Warnings", 1)[1]
        self.assertIn('[2] condition "Has email" leads nowhere', warnings)
        self.assertIn('[3] limit "Cap" leads nowhere', warnings)
        self.assertNotIn('[4] limit "Cap ok" leads nowhere', warnings)

    def test_error_response(self):
        r = run(FIXTURES / "denied.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Loomi Connect returned an error: [ACCESS_DENIED]", r.stderr)
        self.assertIn("don't treat it as 'nothing found'", r.stderr)


if __name__ == "__main__":
    unittest.main()
