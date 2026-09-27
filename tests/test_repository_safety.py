"""Guards for a public repository: no personal data, keys or local paths get committed."""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def tracked_files():
    try:
        output = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [ROOT / name for name in output.decode("utf-8").split("\0") if name]


def test_data_and_runtime_folders_are_ignored():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    required = {"config.json", "data/", "logs/", "models/", "runtime/", ".venv/"}
    assert required <= {line.strip() for line in text.splitlines()}


# Things that would reveal someone's identity, machine or account if committed.
PERSONAL = [
    re.compile(r"[A-Za-z]:\\Users\\(?!<)[A-Za-z]", re.IGNORECASE),     # Windows home folders
    re.compile(r"/(?:Users|home)/(?!runner/|<|user/|you/|\$)[a-z][\w.-]+/", re.IGNORECASE),
    re.compile(r"sgnl://linkdevice\?uuid=[\w-]{16,}"),                 # real link codes
    re.compile(r"\+(?!1555555)\d{10,14}\b"),                            # phone numbers (555 fictional range allowed)
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp|gho|github_pat|sk|xox[bp])_[A-Za-z0-9]{20,}"),
]


def test_no_personal_data_in_tracked_text_files():
    offenders = []
    for path in tracked_files():
        if path.suffix.lower() in {".png", ".ico", ".icns", ".m4a", ".wav", ".lock"} or path.name == "pnpm-lock.yaml":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for pattern in PERSONAL:
            match = pattern.search(text)
            if match:
                offenders.append(f"{path.relative_to(ROOT)}: {match.group(0)!r}")
    assert not offenders, "Personal data in tracked files:\n" + "\n".join(offenders)
