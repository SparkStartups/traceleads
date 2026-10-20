import subprocess
import sys
from dataclasses import astuple

import duckdb
import pytest

from leads.config import CATEGORIES, CITY, CITY_BOUNDS, LEGAL_FORMS, MATCHING, generic_words
from leads.tracking import Run
from leads.warehouse import PUBLISH_ATTEMPTS, PublishError, Warehouse, publish_on_success


def table_names(warehouse: Warehouse) -> set[str]:
    tables = warehouse.con.execute("SELECT schema_name, table_name FROM duckdb_tables()")
    return {f"{schema}.{name}" for schema, name in tables.fetchall()}


def file_rows(path, sql: str) -> list[tuple]:
    with duckdb.connect(path, read_only=True) as con:
        return con.execute(sql).fetchall()


def test_reopening_keeps_the_runs_recorded(tmp_path, sql_dir, month):
    path = tmp_path / "reopened.duckdb"
    for _ in range(2):
        with Warehouse.open(path, sql_dir, tmp_path) as warehouse, Run.start(warehouse.con, month):
            pass
    assert file_rows(path, "SELECT count(*) FROM meta.pipeline_runs") == [(2,)]


def test_the_ref_tables_hold_the_configuration_once(tmp_path, sql_dir):
    path = tmp_path / "configured.duckdb"
    for _ in range(2):  # reopening writes them again
        with Warehouse.open(path, sql_dir, tmp_path):
            pass
    forms = "SELECT code, abbreviation, name, named_after_owner FROM ref.legal_forms"
    assert file_rows(path, forms) == [astuple(form) for form in LEGAL_FORMS]
    pairs = "SELECT category, google_category FROM ref.google_categories"
    assert file_rows(path, pairs) == [
        (category.key, name) for category in CATEGORIES for name in category.google_categories
    ]
    assert file_rows(path, "SELECT word FROM ref.generic_words") == [
        (word,) for word in generic_words()
    ]
    assert file_rows(path, "SELECT * FROM ref.city") == [(CITY, *astuple(CITY_BOUNDS))]
    classes = "SELECT category, activity_class FROM ref.activity_classes"
    assert file_rows(path, classes) == [
        (category.key, code) for category in CATEGORIES for code in category.activity_classes
    ]
    assert file_rows(path, "SELECT * FROM ref.matching") == [astuple(MATCHING)]


def test_model_files_are_numbered_and_ordered_per_layer(warehouse, write_model):
    for name in ["stg/20_b.sql", "stg/10_a.sql", "stg/draft_c.sql", "int/10_other.sql"]:
        write_model(name, "SELECT 1;")
    assert [path.name for path in warehouse.model_files("stg")] == ["10_a.sql", "20_b.sql"]
    assert warehouse.model_files("empty") == []


def test_layer_creates_its_schema_and_models_read_the_run_s_month(warehouse, run, write_model):
    write_model("stg/10_month.sql", "CREATE TABLE stg.t AS SELECT getvariable('snapshot_month');")
    warehouse.run_layer(run, "stg")
    assert warehouse.con.execute("SELECT * FROM stg.t").fetchall() == [(run.snapshot_month,)]


def test_a_failed_model_stops_its_layer_and_is_named(warehouse, run, write_model, caplog):
    write_model("stg/10_good.sql", "CREATE TABLE stg.ok AS SELECT 1 AS x;")
    write_model("stg/20_bad.sql", "SELECT * FROM nope;")
    write_model("stg/30_later.sql", "CREATE TABLE stg.later AS SELECT 1 AS x;")

    with pytest.raises(duckdb.CatalogException):
        warehouse.run_layer(run, "stg")

    assert {"stg.ok", "stg.later"} & table_names(warehouse) == {"stg.ok"}
    assert "2026-10 stg/20_bad.sql failed after" in caplog.text


def test_models_read_files_by_name_from_the_input_dirs(tmp_path, sql_dir, write_model, month):
    inputs = [tmp_path / "snapshot", tmp_path / "labels"]
    for number, directory in enumerate(inputs):
        directory.mkdir()
        duckdb.sql(f"SELECT {number} AS x").write_parquet(
            str(directory / f"source{number}.parquet")
        )
    write_model(
        "stg/10_read.sql",
        "CREATE TABLE stg.t AS SELECT x FROM 'source0.parquet' UNION ALL "
        "SELECT x FROM 'source1.parquet';",
    )
    with (
        Warehouse.open(tmp_path / "w.duckdb", sql_dir, *inputs) as warehouse,
        Run.start(warehouse.con, month) as run,
    ):
        warehouse.run_layer(run, "stg")
        assert warehouse.con.execute("SELECT x FROM stg.t ORDER BY x").fetchall() == [(0,), (1,)]


def build_month(path, sql_dir, month, *, fail: bool = False) -> None:
    with (
        publish_on_success(path) as working_copy,
        Warehouse.open(working_copy, sql_dir, path.parent) as warehouse,
        Run.start(warehouse.con, month),
    ):
        if fail:
            raise RuntimeError("step failed")


def test_publish_replaces_the_warehouse_and_leaves_no_working_copy(tmp_path, sql_dir, month):
    path = tmp_path / "wh.duckdb"
    november = month.replace(month=11)
    build_month(path, sql_dir, month)
    build_month(path, sql_dir, november)

    assert file_rows(path, "SELECT snapshot_month FROM meta.pipeline_runs") == [(november,)]
    assert sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".duckdb") == ["wh.duckdb"]


KILLED_BUILD = (
    "import duckdb, os, sys\n"
    "con = duckdb.connect(sys.argv[1])\n"
    "con.execute('CREATE TABLE leftover_checkpointed AS SELECT 1')\n"
    "con.execute('CHECKPOINT')\n"
    "con.execute('CREATE TABLE leftover_logged AS SELECT 1')\n"
    "os._exit(0)\n"
)


@pytest.mark.parametrize("published", [False, True], ids=["first-build", "later-build"])
def test_working_copy_left_by_a_killed_build_is_discarded(tmp_path, sql_dir, month, published):
    path = tmp_path / "wh.duckdb"
    if published:
        build_month(path, sql_dir, month)
    subprocess.run(
        [sys.executable, "-c", KILLED_BUILD, str(tmp_path / "wh.building.duckdb")], check=True
    )
    assert (tmp_path / "wh.building.duckdb.wal").exists()

    build_month(path, sql_dir, month.replace(month=11))

    assert file_rows(path, "SELECT count(*) FROM meta.pipeline_runs") == [(1,)]
    leftovers = "SELECT count(*) FROM duckdb_tables() WHERE table_name LIKE 'leftover%'"
    assert file_rows(path, leftovers) == [(0,)]


def test_a_failed_build_keeps_the_published_file_and_leaves_its_own(tmp_path, sql_dir, month):
    path = tmp_path / "wh.duckdb"
    build_month(path, sql_dir, month)

    with pytest.raises(RuntimeError):
        build_month(path, sql_dir, month.replace(month=11), fail=True)

    assert file_rows(path, "SELECT snapshot_month FROM meta.pipeline_runs") == [(month,)]
    assert (tmp_path / "wh.building.duckdb").exists()  # for inspection, until the next build


def test_publish_waits_until_readers_close_the_file(tmp_path, sql_dir, month, lock_file):
    path = tmp_path / "wh.duckdb"
    lock_file(path, times=PUBLISH_ATTEMPTS - 1)
    build_month(path, sql_dir, month)
    assert file_rows(path, "SELECT count(*) FROM meta.pipeline_runs") == [(1,)]


def test_publish_gives_up_while_the_file_stays_open(tmp_path, sql_dir, month, lock_file):
    path = tmp_path / "wh.duckdb"
    build_month(path, sql_dir, month)
    lock_file(path, times=PUBLISH_ATTEMPTS)

    with pytest.raises(PublishError, match="close it and rerun"):
        build_month(path, sql_dir, month.replace(month=11))

    assert file_rows(path, "SELECT snapshot_month FROM meta.pipeline_runs") == [(month,)]


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows refuses to replace an open file")
def test_open_reader_blocks_publishing_on_windows(tmp_path, sql_dir, month, no_publish_delay):
    path = tmp_path / "wh.duckdb"
    build_month(path, sql_dir, month)
    with duckdb.connect(path, read_only=True), pytest.raises(PublishError):
        build_month(path, sql_dir, month.replace(month=11))
