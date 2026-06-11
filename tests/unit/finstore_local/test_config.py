"""finstore-local settings: SimpleFIN access URL validation + dashboard knobs."""
import pytest
from pydantic import ValidationError


def test_defaults():
    from finstore_local.config import Settings
    s = Settings(_env_file=None)
    assert s.simplefin_access_url is None
    assert s.chunk_window_days == 90
    assert s.simplefin_max_retries == 1


def test_access_url_requires_https():
    from finstore_local.config import Settings
    with pytest.raises(ValidationError):
        Settings(_env_file=None, simplefin_access_url="http://user:pass@host/path")


def test_access_url_requires_credentials():
    from finstore_local.config import Settings
    with pytest.raises(ValidationError):
        Settings(_env_file=None, simplefin_access_url="https://host/path")


def test_valid_access_url():
    from finstore_local.config import Settings
    s = Settings(
        _env_file=None,
        simplefin_access_url="https://user:pass@bridge.simplefin.org/simplefin/abc",
    )
    assert s.simplefin_access_url is not None


def test_chunk_window_days_bounds():
    from finstore_local.config import Settings
    with pytest.raises(ValidationError):
        Settings(_env_file=None, chunk_window_days=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, chunk_window_days=91)
