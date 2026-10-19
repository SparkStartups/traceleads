import os
import shutil
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from leads import tracking
from leads import warehouse as warehouse_module
from leads.collect import fetch, jar
from leads.config import Settings
from leads.tracking import Run
from leads.warehouse import META_SQL, Warehouse

REPO_SQL_DIR = Path(__file__).resolve().parents[1] / "sql"

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


@dataclass(frozen=True)
class RawSources:
    """Small but realistic raw files of every source for one snapshot month."""

    month: date

    def jar_csv(self) -> bytes:
        return ("\n".join(JAR_LINES) + "\n").encode()

    def write(self, settings: Settings) -> None:
        """Put the files in the month's raw folders, as a finished download leaves them."""
        path = settings.raw_dir("jar", self.month) / jar.FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.jar_csv())


@dataclass(frozen=True)
class FakeResponse:
    status_code: int
    content: bytes


@dataclass
class FakeSession:
    """Stands in for the curl_cffi session: answers each request with the next queued reply."""

    options: dict = field(default_factory=dict)
    requests: list[tuple[str, str]] = field(default_factory=list)  # (method, url)
    replies: list[FakeResponse | Exception] = field(default_factory=list)
    waits: list[float] = field(default_factory=list)  # between retries, recorded instead of slept
    closed: bool = False

    def reply(self, content: bytes = b"", status: int = 200) -> None:
        self.replies.append(FakeResponse(status, content))

    def fail(self, error: Exception) -> None:
        self.replies.append(error)

    def request(self, method: str, url: str) -> FakeResponse:
        self.requests.append((method, url))
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
