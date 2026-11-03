"""Tests for grid_positions.py, shared byte-identically by brand-performance-review, product-opportunity-finder
and new-arrivals-tracker. The grid is synthetic."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plugins/loomi-discovery/skills/brand-performance-review/scripts/grid_positions.py"
GRID = {"success": True, "data": {"response": {"numFound": 3, "docs": [
    {"pid": "p1", "title": "Rain jacket", "brand": "Northwind"},
    {"docType": "content", "slots": [{"id": "s1"}], "title": "Autumn sale banner"},
    {"pid": "p2", "title": "Fleece", "brand": "Contoso"},
    {"pid": "p3", "title": "Boots", "brand": "Contoso"}]}}}


class GridPositionsTest(unittest.TestCase):
    def test_banner_rows_are_not_products(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grid.json"
            path.write_text(json.dumps(GRID), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(path), "--pids", "p2,p3", "--brand", "Contoso",
                                "--top", "2"], capture_output=True, text=True, encoding="utf-8", cwd=tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual((out["rows_fetched"], out["banner_rows_skipped"]), (3, 1))
        # The banner doesn't push p2 down to position 3.
        self.assertEqual(out["positions"]["p2"]["position"], 2)
        self.assertEqual(out["positions"]["p3"]["position"], 3)
        self.assertEqual(out["brand"]["Contoso"]["in_top"], 1)
        self.assertNotIn("Autumn sale banner", r.stdout)


if __name__ == "__main__":
    unittest.main()
