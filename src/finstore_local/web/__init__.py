"""finstore-local FastAPI app — the dashboard."""
from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp

if TYPE_CHECKING:
    from finstore_local.config import Settings


_AUTH_OPEN = ("/login", "/logout")
_LOOPBACK = ("127.0.0.1", "::1", "localhost")


class _AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, access_code: str | None) -> None:
        super().__init__(app)
        self._code = access_code

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not self._code:
            return await call_next(request)
        if request.client and request.client.host in _LOOPBACK:
            return await call_next(request)
        path = request.url.path
        if any(path.startswith(p) for p in _AUTH_OPEN):
            return await call_next(request)
        if request.session.get("authenticated"):
            return await call_next(request)
        return RedirectResponse(url="/login", status_code=302)


def create_app(data_dir: Path, settings: Settings) -> FastAPI:
    app = FastAPI(title="finstore")

    secret_key = settings.web_secret_key or secrets.token_hex(32)
    app.add_middleware(_AuthMiddleware, access_code=settings.web_access_code)
    app.add_middleware(SessionMiddleware, secret_key=secret_key)

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    from finstore_local.web.jobs import get_registry
    from finstore_local.web.router import create_router
    get_registry().reset()
    app.include_router(create_router(data_dir=data_dir, settings=settings, templates=templates))

    return app


__all__ = ["create_app"]
