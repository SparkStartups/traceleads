import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path

import duckdb
import pytest
import typer
from typer.testing import CliRunner

from leads.cli import app, parse_month
from leads.config import Settings, current_month
from leads.warehouse import PUBLISH_ATTEMPTS

SEPTEMBER, OCTOBER = date(2026, 9, 1), date(2026, 10, 1)

runner = CliRunner()


def built_months(root: Path) -> list[date]:
    with duckdb.connect(Settings(root).warehouse_path, read_only=True) as con:
        runs = con.execute("SELECT snapshot_month FROM meta.pipeline_runs ORDER BY started_at")
        return [month for (month,) in runs.fetchall()]


@pytest.fixture
def snapshot(bare_project_root: Path) -> Callable[[date], Path]:
    """Create a month's snapshot folder holding one file that names the month."""

    def make(month: date) -> Path:
        folder = Settings(bare_project_root).snapshot_dir(month)
        folder.mkdir(parents=True)
        (folder / "month.csv").write_text(f"month\n{month}\n", encoding="utf-8")
        return folder

    return make


def test_parse_month_strips_whitespace():
    assert parse_month(" 2026-10 ") == date(2026, 10, 1)


@pytest.mark.parametrize("value", ["2026-13", "26-10", "2026/10", "2026-10-01", ""])
def test_parse_month_rejects_invalid(value: str):
    with pytest.raises(typer.BadParameter, match="expected YYYY-MM"):
        parse_month(value)


def test_collect_rejects_an_invalid_month(project_root):
    result = runner.invoke(app, ["collect", "--month", "2026-13"])
    assert result.exit_code == 2
    assert "'2026-13'" in result.output  # Typer wraps the message to the terminal width


def test_collect_writes_the_snapshot_of_a_month(project_root, raw_sources):
    raw_sources(SEPTEMBER).write(Settings(project_root))
    result = runner.invoke(app, ["collect", "--month", "2026-09"])
    assert result.exit_code == 0, result.output
    assert (Settings(project_root).snapshot_dir(SEPTEMBER) / "jar.parquet").exists()


def test_collect_defaults_to_the_current_month(project_root, raw_sources):
    raw_sources(current_month()).write(Settings(project_root))
    result = runner.invoke(app, ["collect"])
    assert result.exit_code == 0, result.output
    assert (Settings(project_root).snapshot_dir(current_month()) / "jar.parquet").exists()


def test_collect_reports_a_month_it_cannot_fetch(project_root, caplog):
    result = runner.invoke(app, ["collect", "--month", "2026-09"])
    assert result.exit_code == 1
    assert "only the current month can be fetched" in caplog.text


def test_collect_reports_a_source_that_changed(project_root, raw_sources, caplog):
    raw = raw_sources(SEPTEMBER)
    raw.write(Settings(project_root))
    path = Settings(project_root).raw_dir("jar", SEPTEMBER) / "JAR_IREGISTRUOTI.csv"
    path.write_bytes(raw.jar_csv().replace(b"stat_kodas", b"statusas"))
    result = runner.invoke(app, ["collect", "--month", "2026-09"])
    assert result.exit_code == 1
    assert "stat_kodas" in caplog.text


def test_build_rebuilds_every_snapshot_month_oldest_first(bare_project_root, snapshot):
    for month in (OCTOBER, SEPTEMBER):
        snapshot(month)
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 0, result.output
    assert built_months(bare_project_root) == [SEPTEMBER, OCTOBER]


def test_each_month_s_models_read_that_month_s_snapshot(bare_project_root, snapshot):
    for month in (SEPTEMBER, OCTOBER):
        snapshot(month)
    (bare_project_root / "sql" / "stg").mkdir()
    (bare_project_root / "sql" / "stg" / "10_read.sql").write_text(
        "CREATE TABLE IF NOT EXISTS stg.seen (built DATE, read DATE);"
        "INSERT INTO stg.seen SELECT getvariable('snapshot_month'), month FROM 'month.csv';",
        encoding="utf-8",
    )
    assert runner.invoke(app, ["build"]).exit_code == 0
    with duckdb.connect(Settings(bare_project_root).warehouse_path, read_only=True) as con:
        seen = con.execute("SELECT built, read FROM stg.seen ORDER BY built").fetchall()
    assert seen == [(SEPTEMBER, SEPTEMBER), (OCTOBER, OCTOBER)]


def test_layers_run_in_order_stg_int_mart(bare_project_root, snapshot):
    snapshot(OCTOBER)
    models = {
        "stg": "CREATE TABLE stg.a AS SELECT 1 AS x;",
        "int": "CREATE TABLE int.b AS SELECT x + 1 AS x FROM stg.a;",
        "mart": "CREATE TABLE mart.c AS SELECT x + 1 AS x FROM int.b;",
    }
    for layer, sql in models.items():
        (bare_project_root / "sql" / layer).mkdir(exist_ok=True)
        (bare_project_root / "sql" / layer / "10_model.sql").write_text(sql, encoding="utf-8")
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 0, result.output
    with duckdb.connect(Settings(bare_project_root).warehouse_path, read_only=True) as con:
        assert con.execute("SELECT x FROM mart.c").fetchall() == [(3,)]


def test_build_without_any_snapshot_stops(bare_project_root, caplog):
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 1
    assert "run `leads collect` first" in caplog.text
    assert not Settings(bare_project_root).warehouse_path.exists()


def test_a_build_replaces_the_warehouse_with_the_snapshots_there_are(bare_project_root, snapshot):
    for month in (SEPTEMBER, OCTOBER):
        snapshot(month)
    assert runner.invoke(app, ["build"]).exit_code == 0
    shutil.rmtree(Settings(bare_project_root).snapshot_dir(SEPTEMBER))
    assert runner.invoke(app, ["build"]).exit_code == 0
    assert built_months(bare_project_root) == [OCTOBER]


def test_a_failed_model_stops_the_build_without_publishing(bare_project_root, snapshot, caplog):
    snapshot(SEPTEMBER)
    assert runner.invoke(app, ["build"]).exit_code == 0
    snapshot(OCTOBER)
    (bare_project_root / "sql" / "mart" / "10_broken.sql").write_text(
        "SELECT * FROM nope;", encoding="utf-8"
    )

    result = runner.invoke(app, ["build"])

    assert result.exit_code == 1
    assert "2026-09 mart/10_broken.sql failed after" in caplog.text
    assert "Table with name nope does not exist" in caplog.text
    assert "the published warehouse was not changed" in caplog.text
    assert built_months(bare_project_root) == [SEPTEMBER]


def test_a_failed_error_check_stops_the_build_after_its_layer(bare_project_root, snapshot, caplog):
    for month in (SEPTEMBER, OCTOBER):
        snapshot(month)
    (bare_project_root / "sql" / "dq").mkdir()
    (bare_project_root / "sql" / "dq" / "stg_always_fails.sql").write_text(
        "SELECT 1 AS x", encoding="utf-8"
    )
    (bare_project_root / "sql" / "int").mkdir()
    (bare_project_root / "sql" / "int" / "10_model.sql").write_text(
        "CREATE TABLE int.t AS SELECT 1 AS x;", encoding="utf-8"
    )

    result = runner.invoke(app, ["build"])

    assert result.exit_code == 1
    assert "failed stg checks: stg_always_fails; the published warehouse" in caplog.text
    assert not Settings(bare_project_root).warehouse_path.exists()
    failed_build = Settings(bare_project_root).warehouse_path.with_name("leads.building.duckdb")
    with duckdb.connect(failed_build, read_only=True) as con:
        failed = con.execute(
            "SELECT check_name FROM meta.dq_results WHERE failing_rows > 0"
        ).fetchall()
        runs = con.execute("SELECT count(*) FROM meta.pipeline_runs").fetchone()
        int_tables = con.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE schema_name = 'int'"
        ).fetchone()
    assert failed == [("stg_always_fails",)]  # September's only: October was never started
    assert runs == (0,)  # a failed run is not recorded
    assert int_tables == (0,)  # the build stopped after the stg checks


def test_build_loads_each_collected_month_into_staging(project_root, collected):
    for month in (SEPTEMBER, OCTOBER):
        collected(month)
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 0, result.output  # every check passes within its own month
    per_month = "SELECT snapshot_month, count(*) FROM stg.{} GROUP BY ALL ORDER BY ALL"
    with duckdb.connect(Settings(project_root).warehouse_path, read_only=True) as con:
        entities = con.execute(per_month.format("jar_entities")).fetchall()
        listings = con.execute(per_month.format("google_listings")).fetchall()
    assert entities == [(SEPTEMBER, 3), (OCTOBER, 3)]
    assert listings == [(SEPTEMBER, 20), (OCTOBER, 20)]
    for month in (SEPTEMBER, OCTOBER):  # no company is flagged in the fixture months
        path = project_root / "output" / f"{month:%Y-%m}" / "leads.csv"
        header = path.read_text(encoding="utf-8")
        assert header.startswith("rank,status,ja_kodas,company,company_address,category,")


def test_build_reports_a_lead_list_left_open(bare_project_root, snapshot, lock_file, caplog):
    snapshot(OCTOBER)
    path = Settings(bare_project_root).leads_csv(OCTOBER)
    lock_file(path, times=PUBLISH_ATTEMPTS)
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 1
    assert "close it and rerun; the warehouse is published, but not this lead list" in caplog.text
    assert Settings(bare_project_root).warehouse_path.exists()
    assert list(path.parent.iterdir()) == [path.with_name("leads.csv.partial")]


def test_build_reports_a_warehouse_left_open(bare_project_root, snapshot, lock_file, caplog):
    snapshot(SEPTEMBER)
    lock_file(Settings(bare_project_root).warehouse_path, times=PUBLISH_ATTEMPTS)
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 1
    assert "close it and rerun; the published warehouse was not changed" in caplog.text
