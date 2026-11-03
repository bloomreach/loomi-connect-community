"""Fixtures are data. Code that builds them belongs in the test that uses it (writing to a temp folder),
not under tests/fixtures. The fake repo trees the validator tests use (tests/fixtures/repo/) are the exception."""
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class FixturesTest(unittest.TestCase):
    def test_no_code_in_fixtures(self):
        out = subprocess.run(["git", "ls-files", "tests/fixtures"], cwd=REPO, capture_output=True, text=True, check=True)
        code = [p for p in out.stdout.split() if p.endswith(".py") and not p.startswith("tests/fixtures/repo/")]
        self.assertEqual(code, [], "move fixture generators into the tests that use them")


if __name__ == "__main__":
    unittest.main()
