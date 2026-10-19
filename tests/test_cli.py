import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from leads.cli import app
from leads.config import Settings
from leads.warehouse import PUBLISH_ATTEMPTS

SEPTEMBER, OCTOBER = date(2026, 9, 1), date(2026, 10, 1)

runner = CliRunner()


def built_months(root: Path) -> list[date]:
    with duckdb.connect(Settings(root).warehouse_path, read_only=True) as con:
        runs = con.execute("SELECT snapshot_month FROM meta.pipeline_runs ORDER BY started_at")
        return [month for (month,) in runs.fetchall()]


@pytest.fixture
def snapshot(project_root: Path) -> Callable[[date], Path]:
    """Create a month's snapshot folder holding one file that names the month."""

    def make(month: date) -> Path:
        folder = Settings(project_root).snapshot_dir(month)
        folder.mkdir(parents=True)
        (folder / "month.csv").write_text(f"month\n{month}\n", encoding="utf-8")
        return folder

    return make


def test_build_rebuilds_every_snapshot_month_oldest_first(project_root, snapshot):
    for month in (OCTOBER, SEPTEMBER):
        snapshot(month)
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 0, result.output
    assert built_months(project_root) == [SEPTEMBER, OCTOBER]


def test_each_month_s_models_read_that_month_s_snapshot(project_root, snapshot):
    for month in (SEPTEMBER, OCTOBER):
        snapshot(month)
    (project_root / "sql" / "stg").mkdir()
    (project_root / "sql" / "stg" / "10_read.sql").write_text(
        "CREATE TABLE IF NOT EXISTS stg.seen (built DATE, read DATE);"
        "INSERT INTO stg.seen SELECT getvariable('snapshot_month'), month FROM 'month.csv';",
        encoding="utf-8",
    )
    assert runner.invoke(app, ["build"]).exit_code == 0
    with duckdb.connect(Settings(project_root).warehouse_path, read_only=True) as con:
        seen = con.execute("SELECT built, read FROM stg.seen ORDER BY built").fetchall()
    assert seen == [(SEPTEMBER, SEPTEMBER), (OCTOBER, OCTOBER)]


def test_layers_run_in_order_stg_int_mart(project_root, snapshot):
    snapshot(OCTOBER)
    models = {
        "stg": "CREATE TABLE stg.a AS SELECT 1 AS x;",
        "int": "CREATE TABLE int.b AS SELECT x + 1 AS x FROM stg.a;",
        "mart": "CREATE TABLE mart.c AS SELECT x + 1 AS x FROM int.b;",
    }
    for layer, sql in models.items():
        (project_root / "sql" / layer).mkdir()
        (project_root / "sql" / layer / "10_model.sql").write_text(sql, encoding="utf-8")
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 0, result.output
    with duckdb.connect(Settings(project_root).warehouse_path, read_only=True) as con:
        assert con.execute("SELECT x FROM mart.c").fetchall() == [(3,)]


def test_build_without_any_snapshot_stops(project_root, caplog):
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 1
    assert "no snapshot in" in caplog.text
    assert not Settings(project_root).warehouse_path.exists()


def test_a_build_replaces_the_warehouse_with_the_snapshots_there_are(project_root, snapshot):
    for month in (SEPTEMBER, OCTOBER):
        snapshot(month)
    assert runner.invoke(app, ["build"]).exit_code == 0
    shutil.rmtree(Settings(project_root).snapshot_dir(SEPTEMBER))
    assert runner.invoke(app, ["build"]).exit_code == 0
    assert built_months(project_root) == [OCTOBER]


def test_a_failed_model_stops_the_build_without_publishing(project_root, snapshot):
    snapshot(SEPTEMBER)
    assert runner.invoke(app, ["build"]).exit_code == 0
    snapshot(OCTOBER)
    (project_root / "sql" / "mart").mkdir()
    (project_root / "sql" / "mart" / "10_broken.sql").write_text(
        "SELECT * FROM nope;", encoding="utf-8"
    )

    result = runner.invoke(app, ["build"])

    assert result.exit_code == 1
    assert isinstance(result.exception, duckdb.CatalogException)
    assert built_months(project_root) == [SEPTEMBER]


def test_build_reports_a_warehouse_left_open(project_root, snapshot, lock_file, caplog):
    snapshot(SEPTEMBER)
    lock_file(Settings(project_root).warehouse_path, times=PUBLISH_ATTEMPTS)
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 1
    assert "close it and rerun; the published warehouse was not changed" in caplog.text
