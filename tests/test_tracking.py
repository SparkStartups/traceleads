import logging
import re
import subprocess
from datetime import UTC, datetime

import pytest

from leads.tracking import UNKNOWN_SHA, Run, git_sha, new_run_id


def test_run_id_is_the_month_then_the_start_time_and_unique(month):
    first, second = new_run_id(month), new_run_id(month)
    assert re.fullmatch(r"202610-\d{8}T\d{6}-[0-9a-f]{6}", first)
    assert first != second


@pytest.mark.parametrize(
    ("returncode", "stdout", "sha"),
    [(0, "abc1234\n", "abc1234"), (128, "", UNKNOWN_SHA)],
    ids=["in-a-repository", "outside-a-repository"],
)
def test_git_sha_asks_git(monkeypatch, returncode, stdout, sha):
    monkeypatch.setattr(
        subprocess, "run", lambda args, **_: subprocess.CompletedProcess(args, returncode, stdout)
    )
    assert git_sha() == sha


def test_git_sha_is_unknown_without_git(monkeypatch):
    monkeypatch.setenv("PATH", "")
    assert git_sha() == UNKNOWN_SHA


def test_a_run_is_recorded_once_it_succeeds(warehouse, month, caplog):
    caplog.set_level(logging.INFO)
    with Run.start(warehouse.con, month) as run:
        assert warehouse.con.execute("SELECT count(*) FROM meta.pipeline_runs").fetchone() == (0,)
        with run.step("stg/10_a.sql"):
            during = datetime.now(UTC)
    recorded = warehouse.con.execute(
        "SELECT run_id, snapshot_month, git_sha, ? BETWEEN started_at AND finished_at "
        "FROM meta.pipeline_runs",
        [during],
    ).fetchall()
    assert recorded == [(run.run_id, month, "test", True)]
    assert "2026-10 stg/10_a.sql took" in caplog.text


@pytest.mark.parametrize("error", [RuntimeError("source file missing"), KeyboardInterrupt()])
def test_a_failed_run_is_logged_and_not_recorded(warehouse, month, caplog, error):
    with pytest.raises(type(error)), Run.start(warehouse.con, month) as run, run.step("load"):
        raise error
    assert warehouse.con.execute("SELECT count(*) FROM meta.pipeline_runs").fetchone() == (0,)
    failed = [record.getMessage() for record in caplog.records if record.levelname == "ERROR"]
    assert [message.split(" failed after")[0] for message in failed] == [
        "2026-10 load",
        f"run {run.run_id}",
    ]
