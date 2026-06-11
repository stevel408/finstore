import logging
import re
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finstore_local.config import Settings

URL_USERINFO_RE = re.compile(r"(https?://)([^:/]+):([^@/]+)@")
ACCTID_RE = re.compile(r"\bACT[A-Za-z0-9]{37,}\b")


def redact_url(s: str) -> str:
    return URL_USERINFO_RE.sub(r"\1***:***@", s)


def mask_acctid(acctid: str) -> str:
    if not acctid:
        return "(empty)"
    if len(acctid) <= 4:
        return "*" * len(acctid)
    return "*" * (len(acctid) - 4) + acctid[-4:]


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _sanitize(str(record.msg))
        record.args = tuple(_sanitize(str(a)) if isinstance(a, str) else a
                            for a in (record.args or ()))
        return True


def _sanitize(s: str) -> str:
    s = redact_url(s)
    s = ACCTID_RE.sub(lambda m: mask_acctid(m.group(0)), s)
    return s


def configure(settings: "Settings") -> None:
    level_name = "DEBUG" if settings.debug else settings.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.addFilter(SensitiveDataFilter())

    fmt = "%(levelname)-7s %(name)s %(message)s"
    handler.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True

    if settings.debug:
        _print_debug_banner()


def _print_debug_banner() -> None:
    banner = (
        "=" * 60 + "\n"
        "DEBUG=1 — full-payload logging is ON. Backend responses\n"
        "and transaction data WILL be logged.\n"
        "Disable in production by removing DEBUG from .env.\n"
        + "=" * 60
    )
    print(banner, file=sys.stderr)
