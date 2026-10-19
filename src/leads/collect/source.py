"""A source: its raw files for a month and the fields the system pulls from them."""

import hashlib
import json
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import ClassVar

import duckdb

from leads.collect.fetch import Fetcher


@dataclass(frozen=True)
class RawFile:
    url: str
    path: Path

    @property
    def fetched_at(self) -> datetime:
        """When the file was saved: downloaded, or put there by hand."""
        return datetime.fromtimestamp(self.path.stat().st_mtime, UTC)

    def lineage(self) -> dict[str, str]:
        """Return where the file came from, its SHA-256 and when it was saved."""
        with self.path.open("rb") as file:
            digest = hashlib.file_digest(file, "sha256").hexdigest()
        return {
            "file": self.path.name,
            "url": self.url,
            "sha256": digest,
            "fetched_at": self.fetched_at.isoformat(),
        }


class Source(ABC):
    """Fetches its raw files and writes the fields the system uses to the month's snapshot."""

    name: ClassVar[str]
    period_column: ClassVar[str]  # the snapshot column whose maximum is the data's period

    @abstractmethod
    def fetch(self, fetcher: Fetcher, raw_dir: Path, month: date) -> list[RawFile]:
        """Make sure the raw files for ``month`` are in ``raw_dir`` and return them."""

    @abstractmethod
    def rows(
        self, con: duckdb.DuckDBPyConnection, files: list[RawFile]
    ) -> AbstractContextManager[duckdb.DuckDBPyRelation]:
        """Yield the pulled fields of ``files``, selected by column name."""

    def snapshot(self, con: duckdb.DuckDBPyConnection, files: list[RawFile], out_dir: Path) -> int:
        """Write ``<name>.parquet`` and its manifest ``<name>.json``; return the row count."""
        parquet = out_dir / f"{self.name}.parquet"
        with self.rows(con, files) as rows:
            rows.write_parquet(str(parquet))
        count, period = con.sql(
            f"SELECT count(*), max({self.period_column})::VARCHAR FROM read_parquet(?)",
            params=[str(parquet)],
        ).fetchone()
        manifest = {
            "source": self.name,
            "rows": count,
            "period": period,
            "files": [file.lineage() for file in files],
        }
        (out_dir / f"{self.name}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return count
