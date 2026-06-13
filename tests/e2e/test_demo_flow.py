"""End-to-end smoke test: demo setup → fetch → accounts.

Requires a live network connection to beta-bridge.simplefin.org.

Run with:
    RUN_E2E=1 pytest tests/e2e/ -v

Each test runs the real `finstore` CLI in a subprocess against a temporary
data directory, so it never touches production credentials or data.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

# Stay within SimpleFIN's 45-day advisory window to avoid errlist warnings.
_START_DATE = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")


def _finstore(*args: str, data_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run the finstore CLI against a temp data dir with a clean credential env.

    Passes --env-file pointing at an empty file inside the temp dir so that
    pydantic-settings never reads the project's real .env (which may contain
    SIMPLEFIN_ACCESS_URL or GNC_SFIN_CACHE_DIR).
    """
    blank_env_file = data_dir / ".env"
    blank_env_file.touch()

    env = {
        k: v for k, v in os.environ.items()
        if k not in ("SIMPLEFIN_ACCESS_URL", "GNC_SFIN_CACHE_DIR")
    }
    env["GNC_SFIN_CACHE_DIR"] = str(data_dir)

    return subprocess.run(
        [sys.executable, "-m", "finstore_local.cli", *args, "--env-file", str(blank_env_file)],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture(autouse=True)
def require_e2e() -> None:
    if not os.getenv("RUN_E2E"):
        pytest.skip("set RUN_E2E=1 to run end-to-end tests")


def test_demo_setup_saves_credentials(tmp_path: Path) -> None:
    result = _finstore("setup", "--demo", data_dir=tmp_path)
    assert result.returncode == 0, result.stderr
    creds_file = tmp_path / "tenants" / "local" / "credentials" / "simplefin.bin"
    assert creds_file.exists(), "simplefin.bin was not created"
    assert oct(creds_file.stat().st_mode)[-3:] == "600", "simplefin.bin is not mode 0600"


def test_demo_fetch_populates_storage(tmp_path: Path) -> None:
    setup = _finstore("setup", "--demo", data_dir=tmp_path)
    assert setup.returncode == 0, setup.stderr

    fetch = _finstore("fetch", "--start", _START_DATE, data_dir=tmp_path)
    assert fetch.returncode == 0, fetch.stderr

    meta_file = tmp_path / "meta.json"
    assert meta_file.exists(), "meta.json was not created after fetch"


def test_demo_accounts_lists_results(tmp_path: Path) -> None:
    setup = _finstore("setup", "--demo", data_dir=tmp_path)
    assert setup.returncode == 0, setup.stderr

    fetch = _finstore("fetch", "--start", _START_DATE, data_dir=tmp_path)
    assert fetch.returncode == 0, fetch.stderr

    accounts = _finstore("accounts", data_dir=tmp_path)
    assert accounts.returncode == 0, accounts.stderr
    assert accounts.stdout.strip(), "accounts output was empty"


def test_fetch_without_setup_fails_clearly(tmp_path: Path) -> None:
    result = _finstore("fetch", data_dir=tmp_path)
    assert result.returncode != 0
    assert "finstore setup" in result.stderr
