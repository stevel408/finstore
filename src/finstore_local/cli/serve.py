"""`finstore serve` — boot the finstore dashboard."""
from __future__ import annotations

import sys


def run(
    env_file: str | None = None,
    host: str | None = None,
    port: int | None = None,
    debug: bool = False,
) -> None:
    from finstore_local import logging as flog
    from finstore_local.config import Settings, get_settings, resolve_data_dir

    settings = get_settings()
    overrides: dict[str, object] = {}
    if host:
        overrides["host_bind_address"] = host
    if port:
        overrides["host_port"] = port
    if debug:
        overrides["debug"] = True
    if overrides:
        base = settings.model_dump()
        base["simplefin_access_url"] = (
            settings.simplefin_access_url.get_secret_value()
            if settings.simplefin_access_url is not None
            else None
        )
        settings = Settings(**{**base, **overrides})

    flog.configure(settings)

    try:
        data_dir = resolve_data_dir(settings, create=True)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

    import uvicorn

    from finstore_local.web import create_app
    application = create_app(data_dir=data_dir, settings=settings)
    uvicorn.run(
        application,
        host=settings.host_bind_address,
        port=settings.host_port,
        log_config=None,
        lifespan="on",
    )
