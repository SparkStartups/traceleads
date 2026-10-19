from datetime import date

from leads.config import Settings, current_month


def test_snapshot_months_are_the_month_directories_oldest_first(tmp_path):
    settings = Settings(tmp_path)
    for name in ("2026-10", "2025-12", "2026-09", "notes", "temp-01", "2026-11.building"):
        (settings.snapshots_dir / name).mkdir(parents=True)
    (settings.snapshots_dir / "2026-12").write_text("a file, not a snapshot", encoding="utf-8")
    assert settings.snapshot_months() == [date(2025, 12, 1), date(2026, 9, 1), date(2026, 10, 1)]


def test_current_month_is_the_first_day_of_today_s_month():
    today = date.today()
    assert current_month() == date(today.year, today.month, 1)


def test_no_snapshots_give_no_months(tmp_path):
    assert Settings(tmp_path).snapshot_months() == []
