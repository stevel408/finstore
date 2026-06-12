"""Persistent credential store for the local app.

Stores the SimpleFIN access URL in {data_dir}/credentials.json (mode 0o600).
Resolution order (see docs/decisions/13-credentials-file-in-data-dir.md):
  1. SIMPLEFIN_ACCESS_URL env var  — honoured by Settings, takes priority
  2. credentials.json              — written by `finstore setup`
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_FILENAME = "credentials.json"


def save(data_dir: Path, access_url: str) -> None:
    path = data_dir / _FILENAME
    path.write_text(json.dumps({"access_url": access_url}))
    os.chmod(path, 0o600)


def load(data_dir: Path) -> str | None:
    path = data_dir / _FILENAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        url = data.get("access_url")
        return str(url) if url is not None else None
    except (json.JSONDecodeError, OSError, AttributeError):
        return None
