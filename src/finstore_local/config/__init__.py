"""finstore-local configuration. Reads `.env` for SimpleFIN credentials, data
directory, dashboard settings, and logging knobs.

The data directory env var is still `GNC_SFIN_CACHE_DIR` for Step 1 — both
apps read it so they share one cache. Plan §8 renames to `FINSTORE_DATA_DIR`
in Step 4 along with the gateway shim.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import platformdirs
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    simplefin_access_url: SecretStr | None = None
    debug: bool = False
    log_level: str = "INFO"
    simplefin_timeout_secs: float = 30.0
    simplefin_max_retries: int = 1
    chunk_window_days: int = 90
    gnc_sfin_cache_dir: Path | None = None
    host_bind_address: str = "127.0.0.1"
    host_port: int = 8081  # default differs from gateway's 8080 — two UIs run side-by-side
    web_access_code: str | None = None
    web_secret_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", frozen=True, extra="ignore")

    @field_validator("host_port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError(f"PORT must be 1–65535, got {v}")
        return v

    @field_validator("chunk_window_days")
    @classmethod
    def validate_window(cls, v: int) -> int:
        if not 1 <= v <= 90:
            raise ValueError(f"chunk_window_days must be 1–90, got {v}")
        return v

    @field_validator("simplefin_access_url", mode="before")
    @classmethod
    def validate_access_url(cls, v: object) -> object:
        if v is None:
            return v
        url_str = str(v) if not isinstance(v, str) else v
        parsed = urlparse(url_str)
        if parsed.scheme != "https":
            raise ValueError("SIMPLEFIN_ACCESS_URL must use https://")
        if not parsed.netloc:
            raise ValueError("SIMPLEFIN_ACCESS_URL has no host")
        if "@" not in parsed.netloc:
            raise ValueError("SIMPLEFIN_ACCESS_URL must embed credentials (user:pass@host)")
        return v.rstrip("/") if isinstance(v, str) else v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def load_settings(env_file: str | None = None) -> Settings:
    """Return settings, optionally sourced from an alternate env file.

    When `env_file` is None, returns the cached singleton (same as
    `get_settings()`). When a path is given, constructs a fresh `Settings`
    instance that reads from that file instead of `.env`, bypassing the cache
    so callers with different env files don't clobber each other.
    """
    if env_file is None:
        return get_settings()

    from pydantic_settings import SettingsConfigDict

    class _EnvFileSettings(Settings):
        model_config = SettingsConfigDict(env_file=env_file, frozen=True, extra="ignore")

    return _EnvFileSettings()


def resolve_data_dir(settings: Settings, create: bool = False) -> Path:
    """Resolve the finstore data directory.

    Precedence:
      1. The `GNC_SFIN_CACHE_DIR` env var (kept until Step 4 rename to
         `FINSTORE_DATA_DIR` — see plan §8).
      2. `platformdirs.user_data_dir("gnc-sfin-gateway")` — yields
         `~/Library/Application Support/gnc-sfin-gateway/` on macOS,
         `$XDG_DATA_HOME/gnc-sfin-gateway/` on Linux, and
         `%LOCALAPPDATA%\\gnc-sfin-gateway\\` on Windows.
    """
    if settings.gnc_sfin_cache_dir is not None:
        data_dir = Path(settings.gnc_sfin_cache_dir)
    else:
        data_dir = Path(platformdirs.user_data_dir("gnc-sfin-gateway"))

    if create:
        data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        (data_dir / "accounts").mkdir(mode=0o700, exist_ok=True)
    elif not data_dir.exists():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    return data_dir


__all__ = ["Settings", "get_settings", "load_settings", "resolve_data_dir"]
