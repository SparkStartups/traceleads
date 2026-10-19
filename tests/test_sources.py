import hashlib
import json

import duckdb
import pytest

from leads.collect import jar
from leads.collect.fetch import Fetcher
from leads.collect.jar import Jar
from leads.config import Settings


@pytest.fixture
def settings(tmp_path, raw_sources, month) -> Settings:
    """Return settings whose raw folders hold the fixture files for ``month``."""
    settings = Settings(tmp_path)
    raw_sources(month).write(settings)
    return settings


def snapshot(source, settings, month):
    """Snapshot ``source`` from its saved raw files; return columns, sorted rows and manifest."""
    out_dir = settings.root
    with Fetcher(offline=True) as fetcher, duckdb.connect() as con:
        files = source.fetch(fetcher, settings.raw_dir(source.name, month), month)
        source.snapshot(con, files, out_dir)
        rows = con.sql(f"SELECT * FROM '{out_dir / f'{source.name}.parquet'}' ORDER BY ALL")
        columns, values = rows.columns, rows.fetchall()
    manifest = json.loads((out_dir / f"{source.name}.json").read_text(encoding="utf-8"))
    return columns, values, manifest


def test_jar_snapshot_keeps_the_pulled_columns_and_quoted_names(settings, month):
    columns, rows, manifest = snapshot(Jar(), settings, month)
    assert columns == [
        "ja_kodas",
        "ja_pavadinimas",
        "adresas",
        "ja_reg_data",
        "form_kodas",
        "stat_kodas",
        "formavimo_data",
    ]
    assert rows[1][:3] == (
        "304000002",
        'Advokatų profesinė bendrija "LEGES | LB"',
        "Vilnius, Gedimino pr. 1, LT-01103",
    )
    assert (manifest["source"], manifest["rows"], manifest["period"]) == ("jar", 3, "2026-10-16")


def test_manifest_records_each_raw_file(settings, month):
    *_, manifest = snapshot(Jar(), settings, month)
    (file,) = manifest["files"]
    raw = settings.raw_dir("jar", month) / jar.FILE_NAME
    assert file["file"] == raw.name
    assert file["url"] == "https://www.registrucentras.lt/aduomenys/?byla=JAR_IREGISTRUOTI.csv"
    assert file["sha256"] == hashlib.sha256(raw.read_bytes()).hexdigest()
    assert file["fetched_at"].endswith("+00:00")


def test_snapshot_fails_when_a_source_column_disappears(settings, month):
    raw = settings.raw_dir("jar", month) / jar.FILE_NAME
    raw.write_text(raw.read_text(encoding="utf-8").replace("stat_kodas", "statusas"), "utf-8")
    with pytest.raises(duckdb.BinderException, match="stat_kodas"):
        snapshot(Jar(), settings, month)
