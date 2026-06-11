"""Tests for the JobRegistry that backs the fetch dashboard."""
from __future__ import annotations

from finstore_local.web.jobs import JobRegistry


def test_reset_clears_last_success_at() -> None:
    """create_app() resets the registry on every construction; a stale
    last_success_at from a prior process must not leak into the new app."""
    reg = JobRegistry()
    reg.record_success()
    assert reg.last_success_at is not None

    reg.reset()
    assert reg.last_success_at is None
    assert reg.status()["state"] == "idle"
    assert reg.status()["last_success_at"] is None


def test_reset_clears_job_state() -> None:
    reg = JobRegistry()
    reg._job.state = "error"  # type: ignore[assignment]
    reg._job.error = "boom"
    reg.reset()
    assert reg.status()["state"] == "idle"
    assert reg.status()["error"] is None
