import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from leads.collect import collect_month
from leads.collect.fetch import FetchError
from leads.collect.jar import FILE_NAME
from leads.config import Settings, current_month

SNAPSHOT_FILES = ["jar.json", "jar.parquet"]


@pytest.fixture
def earlier_month() -> date:
    return current_month().replace(year=current_month().year - 1)


@pytest.fixture
def lock_new_snapshot(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """Return a switch that makes renaming a new snapshot fail, as Windows does while it is open."""
    real_rename = Path.rename

    def rename(self: Path, target: Path) -> Path:
        if self.name.endswith(".building"):
            raise PermissionError(13, "a file in the folder is open")
        return real_rename(self, target)

    return lambda: monkeypatch.setattr(Path, "rename", rename)


def jar_rows(settings: Settings, month: date) -> int:
    manifest = settings.snapshot_dir(month) / "jar.json"
    return json.loads(manifest.read_text(encoding="utf-8"))["rows"]


def drop_last_company(settings: Settings, month: date) -> None:
    """Remove the last company from the month's saved JAR file."""
    path = settings.raw_dir("jar", month) / FILE_NAME
    path.write_bytes(b"".join(path.read_bytes().splitlines(keepends=True)[:-1]))


def test_current_month_downloads_every_source(project_root, raw_sources, session):
    month = current_month()
    session.reply(raw_sources(month).jar_csv())

    collect_month(Settings(project_root), month)

    assert len(session.requests) == 1
    snapshot_dir = Settings(project_root).snapshot_dir(month)
    assert sorted(path.name for path in snapshot_dir.iterdir()) == SNAPSHOT_FILES


def test_earlier_month_is_rebuilt_from_its_saved_raw_files(
    project_root, raw_sources, session, earlier_month
):
    raw_sources(earlier_month).write(Settings(project_root))

    collect_month(Settings(project_root), earlier_month)

    assert session.requests == []
    snapshot_dir = Settings(project_root).snapshot_dir(earlier_month)
    assert sorted(path.name for path in snapshot_dir.iterdir()) == SNAPSHOT_FILES


def test_earlier_month_without_raw_files_is_never_fetched(project_root, session, earlier_month):
    with pytest.raises(FetchError, match="only the current month can be fetched"):
        collect_month(Settings(project_root), earlier_month)
    assert session.requests == []
    assert list(Settings(project_root).snapshots_dir.iterdir()) == []


def test_rerun_replaces_the_snapshot(project_root, raw_sources, earlier_month):
    settings = Settings(project_root)
    raw_sources(earlier_month).write(settings)
    collect_month(settings, earlier_month)
    drop_last_company(settings, earlier_month)

    collect_month(settings, earlier_month)

    assert jar_rows(settings, earlier_month) == 2
    assert list(settings.snapshots_dir.iterdir()) == [settings.snapshot_dir(earlier_month)]


def test_failed_rerun_keeps_the_earlier_snapshot(project_root, raw_sources, earlier_month):
    settings = Settings(project_root)
    raw_sources(earlier_month).write(settings)
    collect_month(settings, earlier_month)
    (settings.raw_dir("jar", earlier_month) / FILE_NAME).write_text("<html>", encoding="utf-8")

    with pytest.raises(FetchError, match="replace it"):
        collect_month(settings, earlier_month)

    assert jar_rows(settings, earlier_month) == 3
    assert list(settings.snapshots_dir.iterdir()) == [settings.snapshot_dir(earlier_month)]


def test_a_failed_swap_keeps_the_earlier_snapshot(
    project_root, raw_sources, earlier_month, lock_new_snapshot
):
    settings = Settings(project_root)
    raw_sources(earlier_month).write(settings)
    collect_month(settings, earlier_month)
    drop_last_company(settings, earlier_month)
    snapshot_dir = settings.snapshot_dir(earlier_month)
    lock_new_snapshot()

    with pytest.raises(PermissionError):
        collect_month(settings, earlier_month)

    assert jar_rows(settings, earlier_month) == 3
    assert list(settings.snapshots_dir.iterdir()) == [snapshot_dir]


@pytest.mark.parametrize("swapped", [True, False], ids=["after-the-swap", "during-the-swap"])
def test_a_folder_left_by_a_killed_swap_is_cleared(
    project_root, raw_sources, earlier_month, swapped
):
    settings = Settings(project_root)
    raw_sources(earlier_month).write(settings)
    collect_month(settings, earlier_month)
    snapshot_dir = settings.snapshot_dir(earlier_month)
    replaced = snapshot_dir.with_name(f"{snapshot_dir.name}.replaced")
    if swapped:
        replaced.mkdir()
        (replaced / "jar.json").write_text("an older snapshot", encoding="utf-8")
    else:
        snapshot_dir.rename(replaced)
    drop_last_company(settings, earlier_month)

    collect_month(settings, earlier_month)

    assert jar_rows(settings, earlier_month) == 2
    assert list(settings.snapshots_dir.iterdir()) == [snapshot_dir]


def test_a_failed_swap_after_a_killed_one_keeps_the_last_good_snapshot(
    project_root, raw_sources, earlier_month, lock_new_snapshot
):
    settings = Settings(project_root)
    raw_sources(earlier_month).write(settings)
    collect_month(settings, earlier_month)
    snapshot_dir = settings.snapshot_dir(earlier_month)
    snapshot_dir.rename(snapshot_dir.with_name(f"{snapshot_dir.name}.replaced"))
    drop_last_company(settings, earlier_month)
    lock_new_snapshot()

    with pytest.raises(PermissionError):
        collect_month(settings, earlier_month)

    assert jar_rows(settings, earlier_month) == 3
    assert list(settings.snapshots_dir.iterdir()) == [snapshot_dir]


def test_a_failed_first_swap_leaves_no_snapshot(
    project_root, raw_sources, earlier_month, lock_new_snapshot
):
    settings = Settings(project_root)
    raw_sources(earlier_month).write(settings)
    lock_new_snapshot()

    with pytest.raises(PermissionError, match="open"):
        collect_month(settings, earlier_month)

    assert list(settings.snapshots_dir.iterdir()) == []


def test_working_folder_left_by_a_killed_run_is_reused(project_root, raw_sources, earlier_month):
    settings = Settings(project_root)
    raw_sources(earlier_month).write(settings)
    snapshot_dir = settings.snapshot_dir(earlier_month)
    working = snapshot_dir.with_name(f"{snapshot_dir.name}.building")
    working.mkdir(parents=True)
    (working / "jar.json").write_text("half written", encoding="utf-8")

    collect_month(settings, earlier_month)

    assert jar_rows(settings, earlier_month) == 3
    assert list(settings.snapshots_dir.iterdir()) == [snapshot_dir]
