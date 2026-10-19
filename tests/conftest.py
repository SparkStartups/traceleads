import io
import json
import os
import shutil
import zipfile
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import NamedTuple

import pytest

from leads import tracking
from leads import warehouse as warehouse_module
from leads.collect import fetch, jar, sodra, vmi_taxes
from leads.collect.google_maps import API_KEY_VARIABLE, QUERIES
from leads.config import Settings
from leads.tracking import Run
from leads.warehouse import META_SQL, Warehouse

REPO_SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
FIXTURES = Path(__file__).parent / "fixtures"
# Real Google Maps renders, trimmed: a results list of 20 places, and the page of one place.
LIST_PAGE = (FIXTURES / "maps_list.html").read_text(encoding="utf-8")
PLACE_PAGE = (FIXTURES / "maps_place.html").read_text(encoding="utf-8")
NO_LIST_PAGE = '<html><body><div role="main"></div></body></html>'  # rendered, without places

JAR_LINES = (
    "ja_kodas|ja_pavadinimas|adresas|ja_reg_data|form_kodas|form_pavadinimas|stat_kodas|"
    "stat_pavadinimas|stat_data_nuo|formavimo_data",
    '304000001|UAB "Kavos namai"|Vilnius, Trakų g. 8-5, LT-01132|2019-05-02|310|'
    "Uždaroji akcinė bendrovė|0|Teisinis statusas neįregistruotas|2019-05-02|2026-10-16",
    '304000002|"Advokatų profesinė bendrija ""LEGES | LB"""|Vilnius, Gedimino pr. 1, LT-01103|'
    "2009-09-24|840|Advokatų profesinė bendrija|0|Teisinis statusas neįregistruotas|2009-09-24|"
    "2026-10-16",
    "304000003|Individuali įmonė|Kaunas, Laisvės al. 1, LT-44001|2015-01-10|810|"
    "Individuali įmonė|7|Likviduojamas|2026-01-01|2026-10-15",
)
SODRA_HEADER = (
    "Draudėjo kodas (code)",
    "Juridinių asmenų registro kodas (jarCode)",
    "Pavadinimas (name)",
    "Savivaldybė, kurioje registruota(municipality)",
    "Ekonominės veiklos rūšies kodas(ecoActCode)",
    "Ekonominės veiklos rūšies pavadinimas(ecoActName)",
    "Mėnuo (month)",
    "Vidutinis darbo užmokestis (avgWage)",
    "Apdraustųjų skaičius (numInsured)",
    "Vidutinis darbo užmokestis II (avgWage2)",
    "Apdraustųjų skaičius II (numInsured2)",
    "Įmokų suma (tax)",
)
SODRA_DOTTED_CODE = "Ekonominės veiklos rūšies kodas EVRK(ecoActCodeStr)"  # added in 2026
# (code, jarCode, name, ecoActCode, insured); the last insurer has no Lithuanian company code
SODRA_EMPLOYERS = (
    ("1001", "304000001", "UAB „Kavos namai“", "561100", "5"),
    ("1002", "304000002", "Advokatų profesinė bendrija „LEGES | LB“", "15000", "1"),
    ("3976550", "", "„MSM DIGITAL GROUP GMBH“", "", "1"),
)


@dataclass(frozen=True)
class RawSources:
    """Small but realistic raw files of every source for one snapshot month."""

    month: date

    def jar_csv(self) -> bytes:
        return ("\n".join(JAR_LINES) + "\n").encode()

    def sodra_years(self) -> dict[int, bytes]:
        """Return the zipped CSV of each year Sodra is fetched for, January to its latest month."""
        latest = sodra.months_before(self.month, sodra.LAST_MONTH_BACK)
        first_year = sodra.months_before(self.month, sodra.FIRST_MONTH_BACK).year
        files = {}
        for year in range(first_year, latest.year + 1):
            dotted = year >= 2026
            header = list(SODRA_HEADER)
            if dotted:
                header.insert(5, SODRA_DOTTED_CODE)
            lines = [";".join(header)]
            for month in range(1, 13 if year < latest.year else latest.month + 1):
                for code, jar_code, name, evrk, insured in SODRA_EMPLOYERS:
                    cells = [code, jar_code, f'"{name}"', '"Vilniaus m. sav."', evrk]
                    cells += [evrk, '"Restoranų veikla"'] if dotted else ['"Restoranų veikla"']
                    cells += [f"{year}{month:02d}", "", insured, "", "0", ""]
                    lines.append(";".join(cells))
            files[year] = _zip(f"monthly-{year}.csv", "\n".join(lines) + "\n")
        return files

    def vmi_rows(self) -> list[dict]:
        """Return a closed year, this year's stale and latest rows, IĮ and a foreign payer."""
        year = self.month.year

        def row(code: int | None, name: str, tax_year: int, months: int, amount: float) -> dict:
            company = {"ja_kodas": code} if code else None
            return {
                "mm_kodas": company,
                "pavadinimas": name,
                "metai": tax_year,
                "menuo": months,
                "suma": amount,
                "atnaujinta": "2026-10-08",
            }

        return [
            row(304000001, 'UAB "Kavos namai"', year - 1, 12, 15000.5),
            row(304000001, 'UAB "Kavos namai"', year, 8, 9000.0),
            row(304000001, 'UAB "Kavos namai"', year, 9, 10000.25),
            row(304000003, "Jono Jonaičio IĮ", year - 1, 12, 81.94),
            row(304000004, "Onos Onaitės IĮ „Saulės kepykla“", year - 1, 12, 4210.0),
            row(304000005, 'IĮ "A. Petraičio firma "Ratai"', year - 1, 12, 3100.0),
            row(304000006, 'IĮ "V. Petraičio įmonė"', year - 1, 12, 950.0),
            row(None, "TGW LIMITED", year - 1, 12, 135653.74),
        ]

    def google_pages(self) -> dict[str, str]:
        """Return the rendered page of each query by file name: one list of places, the rest
        rendered without one, which keeps the fixture month small."""
        return {
            query.file_name: LIST_PAGE if query == QUERIES[0] else NO_LIST_PAGE for query in QUERIES
        }

    def write(self, settings: Settings) -> None:
        """Put the files in the month's raw folders, as a finished download leaves them."""
        _write(settings.raw_dir("jar", self.month) / jar.FILE_NAME, self.jar_csv())
        for year, content in self.sodra_years().items():
            path = settings.raw_dir("sodra", self.month) / sodra.FILE_NAME.format(year=year)
            _write(path, content)
        lines = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in self.vmi_rows())
        _write(settings.raw_dir("vmi_taxes", self.month) / vmi_taxes.FILE_NAME, lines.encode())
        for file_name, page in self.google_pages().items():
            _write(settings.raw_dir("google_maps", self.month) / file_name, page.encode())


def _zip(name: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, text.encode())
    return buffer.getvalue()


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


@dataclass(frozen=True)
class FakeResponse:
    status_code: int
    content: bytes


class SentRequest(NamedTuple):
    method: str
    url: str
    headers: dict[str, str] | None
    json: dict | None


@dataclass
class FakeSession:
    """Stands in for the curl_cffi session: answers each request with the next queued reply."""

    options: dict = field(default_factory=dict)
    requests: list[SentRequest] = field(default_factory=list)
    replies: list[FakeResponse | Exception] = field(default_factory=list)
    waits: list[float] = field(default_factory=list)  # between retries, recorded instead of slept
    closed: bool = False

    def reply(self, content: bytes = b"", status: int = 200) -> None:
        self.replies.append(FakeResponse(status, content))

    def fail(self, error: Exception) -> None:
        self.replies.append(error)

    def request(
        self, method: str, url: str, headers: dict[str, str] | None, json: dict | None
    ) -> FakeResponse:
        self.requests.append(SentRequest(method, url, headers, json))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    """Replace the HTTP session of every fetcher, and the waits between its retries."""
    fake = FakeSession()

    def make(**options: object) -> FakeSession:
        fake.options = options
        return fake

    monkeypatch.setattr(fetch.requests, "Session", make)
    monkeypatch.setattr(fetch.time, "sleep", fake.waits.append)
    return fake


@pytest.fixture(autouse=True)
def fixed_git_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make runs record a fixed commit instead of asking git."""
    monkeypatch.setattr(tracking, "git_sha", lambda: "test")


@pytest.fixture
def month() -> date:
    return date(2026, 10, 1)


@pytest.fixture
def raw_sources() -> type[RawSources]:
    return RawSources


@pytest.fixture
def list_page() -> str:
    return LIST_PAGE


@pytest.fixture
def place_page() -> str:
    return PLACE_PAGE


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide the developer's Oxylabs key; the tests that need a key ask for ``api_key``."""
    monkeypatch.delenv(API_KEY_VARIABLE, raising=False)


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(API_KEY_VARIABLE, "test-key")
    return "test-key"


@pytest.fixture
def sql_dir(tmp_path: Path) -> Path:
    """Return an SQL directory with the real meta schema and no models or checks."""
    directory = tmp_path / "models"
    directory.mkdir()
    shutil.copy(REPO_SQL_DIR / META_SQL, directory)
    return directory


@pytest.fixture
def write_model(sql_dir: Path) -> Callable[[str, str], None]:
    """Write ``sql`` to a path relative to the SQL directory, e.g. ``stg/10_a.sql``."""

    def write(relative_path: str, sql: str) -> None:
        path = sql_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sql, encoding="utf-8")

    return write


@pytest.fixture
def warehouse(tmp_path: Path, sql_dir: Path) -> Generator[Warehouse]:
    with Warehouse.open(tmp_path / "test.duckdb", sql_dir, tmp_path) as opened:
        yield opened


@pytest.fixture
def run(warehouse: Warehouse, month: date) -> Generator[Run]:
    with Run.start(warehouse.con, month) as active:
        yield active


@pytest.fixture
def no_publish_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(warehouse_module, "PUBLISH_RETRY_SECONDS", 0)


@pytest.fixture
def lock_file(
    monkeypatch: pytest.MonkeyPatch, no_publish_delay: None
) -> Callable[[Path, int], None]:
    """Make replacing ``path`` fail ``times`` times, as Windows does while a reader has it open."""
    real_replace = os.replace

    def lock(path: Path, times: int) -> None:
        failures = iter(range(times))

        def replace(source: Path, target: Path) -> None:
            if Path(target) == path and next(failures, None) is not None:
                raise PermissionError(13, "The process cannot access the file")
            real_replace(source, target)

        monkeypatch.setattr(os, "replace", replace)

    return lock


@pytest.fixture
def project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a working directory with the repository's SQL files."""
    shutil.copytree(REPO_SQL_DIR, Settings(tmp_path).sql_dir)
    monkeypatch.chdir(tmp_path)
    return tmp_path
