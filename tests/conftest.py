import os
import shutil
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest

from leads import tracking
from leads import warehouse as warehouse_module
from leads.config import Settings
from leads.tracking import Run
from leads.warehouse import META_SQL, Warehouse

REPO_SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


@pytest.fixture(autouse=True)
def fixed_git_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make runs record a fixed commit instead of asking git."""
    monkeypatch.setattr(tracking, "git_sha", lambda: "test")


@pytest.fixture
def month() -> date:
    return date(2026, 10, 1)


@pytest.fixture
def sql_dir(tmp_path: Path) -> Path:
    """Return an SQL directory with the real meta schema and no models."""
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
def warehouse(tmp_path: Path, sql_dir: Path) -> Iterator[Warehouse]:
    with Warehouse.open(tmp_path / "test.duckdb", sql_dir, tmp_path) as opened:
        yield opened


@pytest.fixture
def run(warehouse: Warehouse, month: date) -> Iterator[Run]:
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
