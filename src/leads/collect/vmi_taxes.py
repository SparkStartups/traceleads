"""VMI taxes paid: one row per company and year, from the data.gov.lt API."""

import json
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from urllib.parse import quote

import duckdb

from leads.collect.fetch import Fetcher, write_atomic
from leads.collect.source import RawFile, Source

URL = "https://get.data.gov.lt/datasets/gov/vmi/ja_mokesciai/Moketojas"
FILE_NAME = "vmi_taxes.jsonl"
FIELDS = ("mm_kodas.ja_kodas", "pavadinimas", "metai", "menuo", "suma", "atnaujinta")
# The fields' types, given rather than guessed from the first rows of the file.
COLUMNS = {
    "mm_kodas": "STRUCT(ja_kodas BIGINT)",
    "pavadinimas": "VARCHAR",
    "metai": "BIGINT",
    "menuo": "BIGINT",
    "suma": "DOUBLE",
    "atnaujinta": "DATE",
}
PAGE_SIZE = 20_000
YEARS = 3  # this year to date and the two before, so a closed year exists even in January
# An individual enterprise (IĮ) is named after its owner, and so is its trade name at times
# ("V. Petraičio įmonė", "Onos Petraitienės kavinė"). The snapshot keeps only the last quoted part
# of a name, the trade name even when quotes are nested (IĮ "A. Petraičio firma "Ratai"), and
# drops it when it holds an owner's name: an initial and a name, or a first name and a surname,
# told by their endings. In the genitive most endings are a name's; in the nominative only a
# surname's own suffixes are, since "Raudonas Dviratis" reads like "Jonas Petrauskas". In capitals
# only the endings no common word has count.
# DuckDB runs the patterns: its regular expressions know \p{Lu}, Python's re does not.
LAST_QUOTED = r'[„"“]([^„"“”]+)[“"”][^„"“”]*$'
FIRST_NAME_ENDINGS = ("o", "os", "ės", "aus", "io", "ių", "iaus")
SURNAME_ENDINGS = ("ės", "os", "io", "iaus", "ausko", "insko", "cko", "ovo", "evo", "ūno", "ėno")
SURNAME_ENDINGS_IN_CAPITALS = ("ienės", "aitės", "ytės", "ūtės", "aičio", "avičiaus", "evičiaus")
NOMINATIVE_FIRST_NAME_ENDINGS = ("as", "is", "us", "ys", "a", "ė")
NOMINATIVE_SURNAME_ENDINGS = (
    "ienė",
    "aitė",
    "ytė",
    "ūtė",
    "utė",
    "aitis",
    "ėnas",
    "onis",
    "ūnas",
    "auskas",
    "vičius",
    "inskas",
    "ckas",
)


def _full_name(first: tuple[str, ...], surname: tuple[str, ...], *, capitals: bool = False) -> str:
    word = r"\p{Lu}+" if capitals else r"\p{Lu}\p{Ll}+"
    first, surname = (
        tuple(ending.upper() for ending in endings) if capitals else endings
        for endings in (first, surname)
    )
    return rf"(^|\s){word}({'|'.join(first)})\s+{word}({'|'.join(surname)})(\s|$|[,.])"


OWNER_NAME = "|".join(
    (
        r"(^|[\s.])\p{Lu}\.\s?\p{L}{2,}",
        _full_name(FIRST_NAME_ENDINGS, SURNAME_ENDINGS),
        _full_name(FIRST_NAME_ENDINGS, SURNAME_ENDINGS_IN_CAPITALS, capitals=True),
        _full_name(NOMINATIVE_FIRST_NAME_ENDINGS, NOMINATIVE_SURNAME_ENDINGS),
        _full_name(NOMINATIVE_FIRST_NAME_ENDINGS, NOMINATIVE_SURNAME_ENDINGS, capitals=True),
    )
)

URL_SAFE = '=&()",.>'


class VmiTaxes(Source):
    name = "vmi_taxes"
    period_column = "atnaujinta"

    def fetch(self, fetcher: Fetcher, raw_dir: Path, month: date) -> list[RawFile]:
        """Save every page of the query as one JSON-lines file, unless it is already there."""
        query = (
            f"select(_page,{','.join(FIELDS)})&metai>={month.year - YEARS + 1}&limit({PAGE_SIZE})"
        )
        path = raw_dir / FILE_NAME
        if not path.exists():
            records = _pages(fetcher, query)
            write_atomic(
                path, (json.dumps(r, ensure_ascii=False).encode() + b"\n" for r in records)
            )
        return [RawFile(f"{URL}?{quote(query, safe=URL_SAFE)}", path)]

    @contextmanager
    def rows(
        self, con: duckdb.DuckDBPyConnection, files: list[RawFile]
    ) -> Generator[duckdb.DuckDBPyRelation]:
        (file,) = files
        yield con.sql(
            """
            WITH payers AS (
                SELECT
                    mm_kodas.ja_kodas,
                    nullif(regexp_extract(pavadinimas, ?, 1), '') AS quoted,
                    metai,
                    menuo,
                    suma,
                    atnaujinta
                FROM read_json(?, format = 'newline_delimited', columns = ?)
            )
            SELECT
                ja_kodas,
                CASE WHEN NOT regexp_matches(quoted, ?) THEN quoted END AS trade_name,
                metai,
                menuo,
                suma,
                atnaujinta
            FROM payers
            """,
            params=[LAST_QUOTED, str(file.path), COLUMNS, OWNER_NAME],
        )


def _pages(fetcher: Fetcher, query: str) -> Iterator[dict]:
    """Yield the rows of every page; the API returns a token for the next page until the last."""
    token = None
    while True:
        page = f'&page("{token}")' if token else ""
        data = fetcher.get_json(f"{URL}?{quote(query + page, safe=URL_SAFE)}")
        yield from data["_data"]
        token = data.get("_page", {}).get("next")
        if not token:
            return
