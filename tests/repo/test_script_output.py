"""Every skill script that prints must print UTF-8 whatever the console's encoding.

Windows consoles default to cp1252, so printing a product title or SMS with an emoji (or any character
outside cp1252) raises UnicodeEncodeError, often after --out has already been written. Scripts call
sys.stdout.reconfigure(encoding="utf-8") at the start of main() to avoid that.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = sorted(REPO.glob("plugins/*/skills/*/scripts/*.py"))
PRINTING = [p for p in SCRIPTS if "print(" in p.read_text(encoding="utf-8")]


class ScriptOutputTest(unittest.TestCase):
    def test_printing_scripts_reconfigure_stdout(self):
        missing = [str(p.relative_to(REPO)) for p in PRINTING
                   if 'sys.stdout.reconfigure(encoding="utf-8")' not in p.read_text(encoding="utf-8")]
        self.assertEqual(missing, [], "add sys.stdout.reconfigure(encoding=\"utf-8\") at the start of main()")

    def test_help_runs_on_a_cp1252_console(self):
        env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONDONTWRITEBYTECODE="1")
        with tempfile.TemporaryDirectory() as tmp:
            for p in SCRIPTS:
                r = subprocess.run([sys.executable, str(p), "--help"], cwd=tmp, env=env, capture_output=True, timeout=60)
                self.assertEqual(r.returncode, 0, f"{p.relative_to(REPO)}: {r.stderr.decode('utf-8', 'replace')[-300:]}")


if __name__ == "__main__":
    unittest.main()
