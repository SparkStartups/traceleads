"""Data-quality checks: SQL queries that return the rows breaking a rule."""

import json
import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Self

import duckdb

from leads.tracking import Run

log = logging.getLogger(__name__)

SAMPLE_ROWS = 5

_SEVERITY_PATTERN = re.compile(r"--\s*severity:\s*(\w+)")


class Severity(StrEnum):
    ERROR = "error"
    WARN = "warn"


class DataQualityError(Exception):
    """Raised when a check of severity ``error`` finds failing rows."""


@dataclass(frozen=True)
class Check:
    """A ``dq/<layer>_<name>.sql`` file: one query returning the failing rows."""

    name: str
    layer: str
    severity: Severity
    sql: str

    @classmethod
    def from_file(cls, path: Path, layer: str) -> Self:
        """Read a check; its first line may set ``-- severity: warn`` (default ``error``)."""
        sql = path.read_text(encoding="utf-8")
        match = _SEVERITY_PATTERN.fullmatch(sql.split("\n", 1)[0].strip())
        severity = Severity(match[1]) if match else Severity.ERROR
        return cls(path.stem, layer, severity, sql)

    def evaluate(self, con: duckdb.DuckDBPyConnection, run: Run) -> int:
        """Run the check, record it in ``meta.dq_results`` and return how many rows fail it."""
        rows = con.sql(self.sql)
        (failing,) = rows.aggregate("count(*)").fetchone()
        sample = [
            dict(zip(rows.columns, row, strict=True)) for row in rows.limit(SAMPLE_ROWS).fetchall()
        ]
        con.execute(
            "INSERT INTO meta.dq_results VALUES (?, ?, ?, ?, ?, ?)",
            [
                run.run_id,
                self.name,
                self.layer,
                self.severity,
                failing,
                json.dumps(sample, default=str) if failing else None,
            ],
        )
        if failing:
            level = logging.ERROR if self.severity is Severity.ERROR else logging.WARNING
            log.log(level, "check %s (%s): %d failing rows", self.name, self.severity, failing)
        return failing
