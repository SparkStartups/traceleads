"""Register of Legal Entities (Registrų centras): every registered entity in one CSV file."""

from collections.abc import Generator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import duckdb

from leads.collect.fetch import Fetcher
from leads.collect.source import RawFile, Source

FILE_NAME = "JAR_IREGISTRUOTI.csv"
URL = f"https://www.registrucentras.lt/aduomenys/?byla={FILE_NAME}"
COLUMNS = (
    "ja_kodas",
    "ja_pavadinimas",
    "adresas",
    "ja_reg_data",
    "form_kodas",
    "stat_kodas",
    "formavimo_data",
)


class Jar(Source):
    name = "jar"
    period_column = "formavimo_data"

    def fetch(self, fetcher: Fetcher, raw_dir: Path, month: date) -> list[RawFile]:
        return [RawFile(URL, fetcher.download(URL, raw_dir / FILE_NAME, signature=b"ja_kodas|"))]

    @contextmanager
    def rows(
        self, con: duckdb.DuckDBPyConnection, files: list[RawFile]
    ) -> Generator[duckdb.DuckDBPyRelation]:
        (file,) = files
        yield con.sql(
            f"SELECT {', '.join(COLUMNS)} "
            "FROM read_csv(?, delim = '|', header = true, all_varchar = true)",
            params=[str(file.path)],
        )
