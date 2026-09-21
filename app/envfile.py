"""Load the repo's .env file into the process environment.

The server reads its settings (AKIYESI_LLM_BACKEND, the Anthropic key, the
sender salt) from environment variables. Without this, a key sitting in
.env did nothing unless it was exported by hand in the same terminal.

Rules, kept deliberately small (no third-party dotenv package):
  - KEY=VALUE lines only; blank lines and # comments are skipped.
  - A variable already set in the environment wins over the file, so a
    one-off `AKIYESI_LLM_BACKEND=rule_based python3 -m app.server` still
    works.
  - An empty value is skipped rather than set to "". .env.example ships
    with empty placeholders (AKIYESI_CONFIG_DIR=), and setting one to ""
    would point the config loader at the current directory.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_env_file(path: Path = REPO_ROOT / ".env") -> List[str]:
    """Returns the names of the variables it set (never their values)."""
    path = Path(path)
    if not path.exists():
        return []
    loaded: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not key or not value or key in os.environ:
            continue
        os.environ[key] = value
        loaded.append(key)
    return loaded
