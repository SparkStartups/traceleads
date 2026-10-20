"""DuckDB warehouse: run metadata, configuration tables, layered SQL models, checks, publishing."""

import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path
from typing import Self

import duckdb

from leads.checks import Check, DataQualityError, Severity
from leads.config import (
    CATEGORIES,
    CITY,
    CITY_BOUNDS,
    LEGAL_FORMS,
    MATCHING,
    SCORING,
    SENSITIVITY,
    generic_words,
)
from leads.tracking import Run

META_SQL = "meta.sql"
MODEL_GLOB = "[0-9][0-9]_*.sql"
CHECKS_DIR = "dq"
PUBLISH_ATTEMPTS = 20
PUBLISH_RETRY_SECONDS = 0.25


class PublishError(Exception):
    """Raised when a finished build cannot replace a published file."""


def ref_tables() -> dict[str, list[dict[str, object]]]:
    """Return the configuration the models read, as the rows of each ``ref`` table."""
    return {
        "google_categories": [
            {"category": category.key, "google_category": google_category}
            for category in CATEGORIES
            for google_category in category.google_categories
        ],
        "activity_classes": [
            {"category": category.key, "activity_class": activity_class}
            for category in CATEGORIES
            for activity_class in category.activity_classes
        ],
        "category_explanations": [
            {"category": category.key, "explanation": category.explanation}
            for category in CATEGORIES
        ],
        "generic_words": [{"word": word} for word in generic_words()],
        "legal_forms": [asdict(form) for form in LEGAL_FORMS],
        "city": [{"name": CITY} | asdict(CITY_BOUNDS)],
        "matching": [asdict(MATCHING)],
        "scoring": [asdict(SCORING)],
        "sensitivity": [
            {"gap_ratio": gap_ratio, "min_reviews": min_reviews}
            for gap_ratio, min_reviews in product(SENSITIVITY.gap_ratios, SENSITIVITY.min_reviews)
        ],
    }


@dataclass(frozen=True)
class Warehouse:
    """A DuckDB connection paired with the directory of SQL models it runs."""

    con: duckdb.DuckDBPyConnection
    sql_dir: Path

    @classmethod
    @contextmanager
    def open(cls, path: Path, sql_dir: Path, *input_dirs: Path) -> Generator[Self]:
        """Open or create the warehouse file, ensure the meta schema and write the ref tables.

        Models read their input files by name from ``input_dirs`` (``FROM 'jar.parquet'``).
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        search_path = ",".join(str(directory) for directory in input_dirs)
        with duckdb.connect(path, config={"file_search_path": search_path}) as con:
            warehouse = cls(con, sql_dir)
            warehouse.execute_file(sql_dir / META_SQL)
            warehouse.write_ref()
            yield warehouse

    def write_ref(self) -> None:
        """Write the configuration into the ``ref`` schema, replacing what an earlier run wrote."""
        self.con.execute("CREATE SCHEMA IF NOT EXISTS ref")
        for name, rows in ref_tables().items():
            self.con.execute(
                f"CREATE OR REPLACE TABLE ref.{name} AS SELECT unnest(?, recursive := true)", [rows]
            )

    def execute_file(self, path: Path) -> None:
        self.con.execute(path.read_text(encoding="utf-8"))

    def model_files(self, layer: str) -> list[Path]:
        """Return the SQL model files (``<layer>/NN_name.sql``) in execution order."""
        return sorted((self.sql_dir / layer).glob(MODEL_GLOB))

    def checks(self, layer: str) -> list[Check]:
        """Return the checks of ``layer`` (``dq/<layer>_name.sql``) in name order."""
        paths = sorted((self.sql_dir / CHECKS_DIR).glob(f"{layer}_*.sql"))
        return [Check.from_file(path, layer) for path in paths]

    def run_layer(self, run: Run, layer: str) -> None:
        """Execute every model of ``layer`` as a step of ``run``.

        The layer's schema is created first; models qualify their tables with it (``stg.jar``)
        and read the month with ``getvariable('snapshot_month')``.
        """
        self.con.execute(f"CREATE SCHEMA IF NOT EXISTS {layer}")
        for path in self.model_files(layer):
            with run.step(f"{layer}/{path.name}"):
                self.execute_file(path)

    def run_checks(self, run: Run, layer: str) -> None:
        """Run the checks of ``layer`` as one step of ``run``, recording each result.

        Every check runs before an ``error`` failure is raised, so all results are recorded.
        """
        with run.step(f"{CHECKS_DIR}/{layer}"):
            failed = []
            for check in self.checks(layer):
                if check.evaluate(self.con, run) and check.severity is Severity.ERROR:
                    failed.append(check.name)
            if failed:
                raise DataQualityError(f"failed {layer} checks: {', '.join(failed)}")


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
