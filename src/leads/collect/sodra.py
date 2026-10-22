"""Sodra: insured people per employer and month, one zipped CSV file per year."""

import re
import tempfile
import zipfile
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import duckdb

from leads.collect.fetch import Fetcher, FetchError
from leads.collect.source import RawFile, Source
from leads.config import SCORING

FILE_NAME = "monthly-{year}.csv.zip"
URL = "https://atvira.sodra.lt/imones/downloads/{year}/" + FILE_NAME
ZIP_SIGNATURE = b"PK\x03\x04"
COLUMNS = ("jarCode", "month", "numInsured", "ecoActCode")
# Sodra publishes a month about four weeks after it ends, so its latest month is two months
# before the snapshot month, or three if a release is late; the months staff averages over then
# lie between LAST_MONTH_BACK and FIRST_MONTH_BACK months before.
LAST_MONTH_BACK = 2
FIRST_MONTH_BACK = LAST_MONTH_BACK + SCORING.staff_months

_HEADER_CODE = re.compile(r"\((\w+)\)\s*$")


class Sodra(Source):
    name = "sodra"
    period_column = "month"

    def fetch(self, fetcher: Fetcher, raw_dir: Path, month: date) -> list[RawFile]:
        """Return the files of the years that hold the months staff averages over.

        A new year's file is asked for only once its January can be published.
        """
        first, last = months_before(month, FIRST_MONTH_BACK), months_before(month, LAST_MONTH_BACK)
        files = []
        for year in range(first.year, last.year + 1):
            url = URL.format(year=year)
            path = fetcher.download(url, raw_dir / FILE_NAME.format(year=year), ZIP_SIGNATURE)
            files.append(RawFile(url, path))
        return files

    @contextmanager
    def rows(
        self, con: duckdb.DuckDBPyConnection, files: list[RawFile]
    ) -> Generator[duckdb.DuckDBPyRelation]:
        columns = ", ".join(COLUMNS)
        with tempfile.TemporaryDirectory() as tmp:
            csvs = [_extract(file.path, Path(tmp)) for file in files]
            yield con.sql(
                " UNION ALL ".join(
                    f"SELECT {columns} FROM read_csv(?, delim = ';', header = true, names = ?, "
                    "all_varchar = true)"
                    for _ in csvs
                ),
                params=[value for csv in csvs for value in (str(csv), header_codes(csv))],
            )


def months_before(month: date, count: int) -> date:
    """Return the first day of the month ``count`` months before ``month``."""
    index = month.year * 12 + month.month - 1 - count
    return date(index // 12, index % 12 + 1, 1)


def header_codes(csv: Path) -> list[str]:
    """Return the column names from the code in brackets that ends each header cell.

    The header text differs between years (2026 adds a column), so columns are matched by code.
    """
    with csv.open(encoding="utf-8-sig") as file:
        cells = file.readline().split(";")
    codes = []
    for cell in cells:
        match = _HEADER_CODE.search(cell)
        if match is None:
            raise FetchError(f"{csv.name}: no column code in header cell {cell.strip()!r}")
        codes.append(match[1])
    return codes


def _extract(archive_path: Path, target: Path) -> Path:
    with zipfile.ZipFile(archive_path) as archive:
        (name,) = archive.namelist()
        return Path(archive.extract(name, target))
