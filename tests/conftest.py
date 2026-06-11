from pathlib import Path

import pytest


@pytest.fixture
def tmp_cache(tmp_path: Path) -> Path:
    """Return a temporary cache directory path (not yet created)."""
    return tmp_path / "cache"
