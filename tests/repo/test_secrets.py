"""Repo-wide checks for the charter's "Secrets and keys" rules.

1. No tracked file holds something shaped like a real credential.
2. No skill asks the user for a key, secret, token or password.
"""
import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Shapes of real credentials. Test fixtures use obviously fake values that contain FAKE (for example
# "apisecret-FAKE-3c4d"), and docs use ${VAR} references or <placeholders>, which these don't match.
SECRET_SHAPES = {
    "private key block": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----",
    "GitHub token": r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
    "Anthropic or OpenAI key": r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}\b",
    "AWS access key": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "Slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b",
    "Google API key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "Basic auth header with a real-looking credential":
        r"""["']?Authorization["']?\s*[:=]\s*["']?Basic\s+[A-Za-z0-9+/]{40,}={0,2}""",
    "curl user and password": r"\bcurl\b[^\n]*\s(?:-u|--user)\s+[\"']?[^\s:\"'$<]+:[^\s\"'$<]{8,}",
    "Bloomreach key in a variable": r"""BLOOMREACH_\w*(?:AUTH_KEY|API_SECRET|API_KEY_ID)["']?\s*[:=]\s*["']?(?!\$|<)(?![^"'\s]*FAKE)[A-Za-z0-9+/=_-]{8,}""",
    "Bearer token": r"Bearer\s+[A-Za-z0-9._~+/-]{40,}={0,2}",
    "key assigned in a URL": r"[?&](?:auth_key|api_key|apikey|access_token)=(?![^&\s]*FAKE)[A-Za-z0-9+/=%_-]{16,}",
}

# A skill asking the user to hand over a credential.
ASKS_FOR_KEY = re.compile(
    r"\b(?:paste|enter|provide|give|send|share|type)\s+(?:me\s+|us\s+)?(?:your|the|an?)\s+"
    r"(?:\w+\s+){0,2}(?:api[\s_-]?key|api[\s_-]?secret|secret|auth[\s_-]?key|access[\s_-]?token|token|password)\b", re.I)
# Only a negation right before the verb ("never paste your key") excuses a match.
SAYS_NOT_TO = re.compile(r"\b(?:never|don't|do not|not|nor)\s+(?:\w+\s+)?$", re.I)


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    return [REPO / p for p in out.split("\0") if p]


class SecretsTest(unittest.TestCase):
    def test_no_credential_shaped_strings(self):
        hits = []
        for path in tracked_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for name, pattern in SECRET_SHAPES.items():
                for m in re.finditer(pattern, text):
                    line = text.count("\n", 0, m.start()) + 1
                    hits.append(f"{path.relative_to(REPO)}:{line}: {name}")
        self.assertEqual(hits, [], "remove these and rotate the credential if it was real")

    def test_skills_never_ask_for_keys(self):
        hits = []
        for path in sorted(REPO.glob("plugins/*/skills/*/**/*.md")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                m = ASKS_FOR_KEY.search(line)
                if m and not SAYS_NOT_TO.search(line[:m.start()]):
                    hits.append(f"{path.relative_to(REPO)}:{n}: {line.strip()[:100]}")
        self.assertEqual(hits, [], "skills use the user's own connection and never ask for keys (CHARTER.md)")


if __name__ == "__main__":
    unittest.main()
