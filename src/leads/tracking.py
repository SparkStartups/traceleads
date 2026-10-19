"""Run tracking: each successful run is recorded in ``meta.pipeline_runs``, every step is logged."""

import logging
import subprocess
import time
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Self
from uuid import uuid4

import duckdb

from leads.config import MONTH_FORMAT

log = logging.getLogger(__name__)

UNKNOWN_SHA = "unknown"


@dataclass(frozen=True)
class Run:
    run_id: str
    snapshot_month: date

    @classmethod
    @contextmanager
    def start(cls, con: duckdb.DuckDBPyConnection, snapshot_month: date) -> Generator[Self]:
        """Expose the month to SQL models and yield the run; record it once it succeeds.

        A failed run is only logged: its warehouse is never published.
        """
        run = cls(new_run_id(snapshot_month), snapshot_month)
        con.execute("SET VARIABLE snapshot_month = ?", [snapshot_month])
        started_at = datetime.now(UTC)
        with _timed(f"run {run.run_id}"):
            yield run
        con.execute(
            "INSERT INTO meta.pipeline_runs VALUES (?, ?, ?, ?, current_timestamp)",
            [run.run_id, snapshot_month, git_sha(), started_at],
        )

    def step(self, name: str) -> AbstractContextManager[None]:
        """Log how long a step of the run took, or that it failed."""
        return _timed(f"{self.snapshot_month:{MONTH_FORMAT}} {name}")


def new_run_id(snapshot_month: date) -> str:
    """Return a sortable, unique run id, e.g. ``202610-20261016T175921-494dd1``."""
    return f"{snapshot_month:%Y%m}-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid4().hex[:6]}"


def git_sha() -> str:
    """Return the short commit hash from git, or ``"unknown"`` outside a repository or git."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN_SHA
    return result.stdout.strip() if result.returncode == 0 else UNKNOWN_SHA


@contextmanager
def _timed(label: str) -> Generator[None]:
    started = time.perf_counter()
    try:
        yield
    except BaseException:
        log.error("%s failed after %.2fs", label, time.perf_counter() - started)
        raise
    log.info("%s took %.2fs", label, time.perf_counter() - started)
