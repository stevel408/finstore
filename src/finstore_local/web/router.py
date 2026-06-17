"""finstore dashboard routes. Single router — covers everything."""
from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.responses import Response as _Response
from fastapi.templating import Jinja2Templates

from finstore.storage.exceptions import CacheEmptyError, CacheMissError
from finstore.storage.filesystem import FilesystemStorage
from finstore.storage.validate import validate_cache
from finstore_local.web.jobs import get_registry

if TYPE_CHECKING:
    from finstore_local.config import Settings


def _fmt_epoch(epoch: int | None) -> str:
    if not epoch:
        return "—"
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def create_router(
    data_dir: Path,
    settings: Settings,
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()
    registry = get_registry()
    access_code = settings.web_access_code
    storage = FilesystemStorage(root=data_dir)

    @router.get("/login", response_class=HTMLResponse)
    async def login_get(request: Request, next: str = "/") -> _Response:
        if not access_code or request.session.get("authenticated"):
            return RedirectResponse(url=next or "/", status_code=302)
        return templates.TemplateResponse(request, "login.html", {"next": next, "flash": None})

    @router.post("/login")
    async def login_post(
        request: Request,
        code: str = Form(default=""),
        next: str = Form(default="/"),
    ) -> _Response:
        if access_code and code == access_code:
            request.session["authenticated"] = True
            return RedirectResponse(url=next or "/", status_code=302)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next": next, "flash": {"level": "error", "message": "Incorrect access code."}},
            status_code=401,
        )

    @router.get("/logout")
    async def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)

    @router.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request, flash: str | None = None) -> HTMLResponse:
        flash_obj = {"level": "ok", "message": flash} if flash else None
        try:
            meta = storage.read_meta("local")
            total_txns = sum(a.txn_count for a in meta.accounts.values())
            total_positions = sum(
                a.position_count for a in meta.investment_accounts.values()
            )
            ctx = {
                "meta": meta,
                "last_fetch": _fmt_epoch(meta.last_fetch_at),
                "account_count": len(meta.accounts),
                "investment_account_count": len(meta.investment_accounts),
                "institution_count": len(meta.connections),
                "total_txns": total_txns,
                "total_positions": total_positions,
                "flash": flash_obj,
            }
        except CacheEmptyError:
            ctx = {
                "meta": None,
                "last_fetch": None,
                "account_count": 0,
                "investment_account_count": 0,
                "institution_count": 0,
                "total_txns": 0,
                "total_positions": 0,
                "flash": flash_obj,
            }
        return templates.TemplateResponse(request, "dashboard.html", ctx)

    @router.get("/accounts", response_class=HTMLResponse)
    async def accounts_list(request: Request) -> HTMLResponse:
        try:
            stubs = storage.list_accounts("local")
            formatted = [
                {"stub": s, "last_fetch_fmt": _fmt_epoch(s.last_fetch_at)} for s in stubs
            ]
        except CacheEmptyError:
            formatted = []
        try:
            inv_stubs = storage.list_investment_accounts("local")
            inv_formatted = [
                {"stub": s, "last_fetch_fmt": _fmt_epoch(s.last_fetch_at)}
                for s in inv_stubs
            ]
        except CacheEmptyError:
            inv_formatted = []
        return templates.TemplateResponse(request, "accounts.html", {
            "accounts": formatted,
            "investment_accounts": inv_formatted,
            "flash": None,
        })

    @router.get("/accounts/{display_id}", response_class=HTMLResponse)
    async def account_detail(request: Request, display_id: str) -> _Response:
        try:
            real_acctid = storage.resolve_display_id("local", display_id)
            cached = storage.read_account("local", real_acctid)
        except (CacheMissError, CacheEmptyError):
            return templates.TemplateResponse(
                request,
                "dashboard.html",
                {
                    "meta": None,
                    "last_fetch": None,
                    "account_count": 0,
                    "institution_count": 0,
                    "total_txns": 0,
                    "flash": {"level": "error", "message": f"Account not found: {display_id}"},
                },
                status_code=404,
            )
        sorted_txns = sorted(cached.transactions, key=lambda t: t.posted, reverse=True)
        return templates.TemplateResponse(request, "account_detail.html", {
            "account": cached.account,
            "transactions": sorted_txns,
            "balance_date_fmt": _fmt_epoch(cached.account.balance_date),
            "fmt_epoch": _fmt_epoch,
            "flash": None,
        })

    @router.get("/investment-accounts/{display_id}", response_class=HTMLResponse)
    async def investment_account_detail(
        request: Request, display_id: str
    ) -> _Response:
        try:
            cached = storage.read_investment_account("local", display_id)
        except (CacheMissError, CacheEmptyError):
            return templates.TemplateResponse(
                request,
                "dashboard.html",
                {
                    "meta": None,
                    "last_fetch": None,
                    "account_count": 0,
                    "investment_account_count": 0,
                    "institution_count": 0,
                    "total_txns": 0,
                    "total_positions": 0,
                    "flash": {
                        "level": "error",
                        "message": f"Investment account not found: {display_id}",
                    },
                },
                status_code=404,
            )
        sorted_txns = sorted(
            cached.investment_transactions, key=lambda t: t.trade_date, reverse=True
        )
        securities = storage.read_securities(
            "local",
            ids=tuple(
                (p.security_id_type, p.security_id)
                for p in cached.account.positions
            ) or None,
        )
        sec_map = {(s.uniqueid_type, s.uniqueid): s for s in securities}
        return templates.TemplateResponse(
            request,
            "investment_account_detail.html",
            {
                "account": cached.account,
                "transactions": sorted_txns,
                "sec_map": sec_map,
                "balance_date_fmt": _fmt_epoch(cached.account.balance_date),
                "fmt_epoch": _fmt_epoch,
                "flash": None,
            },
        )

    @router.get("/validate", response_class=HTMLResponse)
    async def validate(request: Request) -> HTMLResponse:
        violations = validate_cache(data_dir)
        return templates.TemplateResponse(request, "validate.html", {
            "violations": violations,
            "flash": None,
        })

    @router.get("/fetch", response_class=HTMLResponse)
    async def fetch_page(request: Request) -> HTMLResponse:
        has_simplefin = settings.simplefin_access_url is not None
        has_snaptrade = bool(settings.snaptrade_client_id and settings.snaptrade_consumer_key)
        return templates.TemplateResponse(request, "fetch.html", {
            "has_any_backend": has_simplefin or has_snaptrade,
            "has_simplefin": has_simplefin,
            "has_snaptrade": has_snaptrade,
            "job": registry.status(),
            "last_success_fmt": _fmt_epoch(registry.last_success_at),
            "flash": None,
        })

    @router.post("/fetch/start")
    async def fetch_start(request: Request) -> RedirectResponse:
        has_simplefin = settings.simplefin_access_url is not None
        has_snaptrade = bool(settings.snaptrade_client_id and settings.snaptrade_consumer_key)
        if has_simplefin or has_snaptrade:
            registry.start(data_dir, settings)
        return RedirectResponse(url="/fetch", status_code=302)

    @router.get("/fetch/status")
    async def fetch_status(request: Request) -> JSONResponse:
        return JSONResponse(registry.status())

    @router.get("/cache/reset", response_class=HTMLResponse)
    async def cache_reset_get(request: Request, account: str | None = None) -> HTMLResponse:
        return templates.TemplateResponse(request, "cache_reset.html", {
            "account": account or "",
            "flash": None,
        })

    @router.post("/cache/reset")
    async def cache_reset_post(
        request: Request,
        account: str = Form(default=""),
        confirm: str = Form(default=""),
    ) -> RedirectResponse:
        if confirm != "on":
            return RedirectResponse(url="/cache/reset", status_code=302)

        if account:
            from finstore.storage.paths import normalize_conn_id
            try:
                meta = storage.read_meta("local")
                acct_meta = meta.accounts.get(account)
                if acct_meta is not None:
                    target = (
                        data_dir
                        / "accounts"
                        / normalize_conn_id(acct_meta.conn_id)
                        / f"{account}.json"
                    )
                    if target.exists():
                        target.unlink()
                meta_path = data_dir / "meta.json"
                if meta_path.exists():
                    raw = json.loads(meta_path.read_text(encoding="utf-8"))
                    raw.get("accounts", {}).pop(account, None)
                    meta_path.write_text(json.dumps(raw), encoding="utf-8")
            except CacheEmptyError:
                pass
            flash_msg = f"Cache entry for {account!r} deleted."
        else:
            shutil.rmtree(data_dir, ignore_errors=True)
            flash_msg = "Cache deleted."

        return RedirectResponse(url=f"/?flash={quote(flash_msg)}", status_code=302)

    return router
