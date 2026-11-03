import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "plugins" / "loomi-discovery" / "skills" / "discovery-experiment-setup" / "scripts"
FIX = ROOT / "tests" / "fixtures" / "discovery"


def run(script, *args):
    """Run a script by its full path from a fresh working folder, as an assistant would."""
    with tempfile.TemporaryDirectory() as tmp:
        return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], cwd=tmp,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)


class SimulateRerankTest(unittest.TestCase):
    def test_help(self):
        for script in ("simulate_rerank.py", "estimate_duration.py"):
            self.assertEqual(run(script, "--help").returncode, 0, script)

    def test_error_returned_as_data_stops(self):
        p = run("simulate_rerank.py", FIX / "denied.json", "--boost-brand", "Contoso")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stdout, "")
        self.assertIn("Loomi Connect returned an error: [ACCESS_DENIED]", p.stderr)

    def test_banner_rows_are_not_products(self):
        grid = {"success": True, "data": {"response": {"docs": [
            {"pid": "p1", "title": "Rain jacket", "brand": "Northwind"},
            {"docType": "content", "slots": [{"id": "s1"}], "title": "Autumn sale banner"},
            {"pid": "p2", "title": "Fleece", "brand": "Contoso"},
            {"pid": "p3", "title": "Rain jacket", "brand": "Fabrikam"}]}}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grid.json"
            path.write_text(json.dumps(grid), encoding="utf-8")
            p = run("simulate_rerank.py", path, "--boost-brand", "Contoso", "--bury-duplicates", "--top", 3)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("Results: 3 products", p.stdout)
        self.assertIn("Left out 1 banner row(s)", p.stdout)
        self.assertNotIn("Autumn sale banner", p.stdout)
        rows = [l for l in p.stdout.splitlines() if l.startswith("| ") and not l.startswith("| New")]
        self.assertEqual(rows, ["| 1 | 2 | Contoso | Fleece |", "| 2 | 1 | Northwind | Rain jacket |",
                                "| 3 | 3 | Fabrikam | Rain jacket |"])
        self.assertIn('["p3"]', p.stdout)


if __name__ == "__main__":
    unittest.main()
