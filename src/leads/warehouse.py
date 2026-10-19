"""DuckDB warehouse: run-metadata schema, layered SQL models and publishing."""

import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Self

import duckdb

from leads.tracking import Run

META_SQL = "meta.sql"
MODEL_GLOB = "[0-9][0-9]_*.sql"
PUBLISH_ATTEMPTS = 20
PUBLISH_RETRY_SECONDS = 0.25


class PublishError(Exception):
    """Raised when a finished build cannot replace a published file."""


class Warehouse:
    """A DuckDB connection paired with the directory of SQL models it runs."""

    def __init__(self, con: duckdb.DuckDBPyConnection, sql_dir: Path) -> None:
        self.con = con
        self.sql_dir = sql_dir

    @classmethod
    @contextmanager
    def open(cls, path: Path, sql_dir: Path, *input_dirs: Path) -> Generator[Self]:
        """Open or create the warehouse file and ensure the meta schema exists.

        Models read their input files by name from ``input_dirs`` (``FROM 'jar.parquet'``).
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        search_path = ",".join(str(directory) for directory in input_dirs)
        with duckdb.connect(path, config={"file_search_path": search_path}) as con:
            warehouse = cls(con, sql_dir)
            warehouse.execute_file(sql_dir / META_SQL)
            yield warehouse

    def execute_file(self, path: Path) -> None:
        self.con.execute(path.read_text(encoding="utf-8"))

    def model_files(self, layer: str) -> list[Path]:
        """Return the SQL model files (``<layer>/NN_name.sql``) in execution order."""
        return sorted((self.sql_dir / layer).glob(MODEL_GLOB))

    def run_layer(self, run: Run, layer: str) -> None:
        """Execute every model of ``layer`` as a step of ``run``.

        The layer's schema is created first; models qualify their tables with it (``stg.jar``)
        and read the month with ``getvariable('snapshot_month')``.
        """
        self.con.execute(f"CREATE SCHEMA IF NOT EXISTS {layer}")
        for path in self.model_files(layer):
            with run.step(f"{layer}/{path.name}"):
                self.execute_file(path)


@contextmanager
def publish_on_success(path: Path) -> Generator[Path]:
    """Yield the path of a new warehouse and publish it as ``path`` if the body succeeds.

    Readers of the published file never see a half-built warehouse. A failed build leaves the new
    file in place for inspection until the next build, and the published file as it was.
    """
    working = path.with_suffix(f".building{path.suffix}")
    working.unlink(missing_ok=True)  # left by a failed or killed build; DuckDB drops its WAL
    yield working
    _replace(working, path)


def _replace(source: Path, target: Path) -> None:
    """Move ``source`` over ``target``, waiting briefly for readers of ``target`` to close it.

    Windows cannot replace a file that another process has open, even read-only.
    """
    for attempt in range(1, PUBLISH_ATTEMPTS + 1):
        try:
            source.replace(target)
            return
        except PermissionError as exc:
            if attempt == PUBLISH_ATTEMPTS:
                raise PublishError(
                    f"{target} stayed open in another program (a SQL client); close it and rerun"
                ) from exc
            time.sleep(PUBLISH_RETRY_SECONDS)
