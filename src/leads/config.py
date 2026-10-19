"""Project paths, the snapshot month and the categories searched for."""

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

MONTH_FORMAT = "%Y-%m"
MONTH_GLOB = "[0-9][0-9][0-9][0-9]-[0-9][0-9]"


def current_month() -> date:
    """Return the first day of the current month."""
    return date.today().replace(day=1)


@dataclass(frozen=True)
class Settings:
    """Filesystem layout relative to the project root, the working directory by default."""

    root: Path = field(default_factory=Path.cwd)

    @property
    def sql_dir(self) -> Path:
        return self.root / "sql"

    @property
    def warehouse_path(self) -> Path:
        return self.root / "warehouse" / "leads.duckdb"

    def raw_dir(self, source: str, month: date) -> Path:
        """Return the folder of ``source``'s files as downloaded for ``month``."""
        return self.root / "data" / "raw" / source / f"{month:{MONTH_FORMAT}}"

    @property
    def snapshots_dir(self) -> Path:
        return self.root / "data" / "snapshots"

    def snapshot_dir(self, month: date) -> Path:
        """Return the folder ``month`` is built from."""
        return self.snapshots_dir / f"{month:{MONTH_FORMAT}}"

    def snapshot_months(self) -> list[date]:
        """Return the months with a snapshot, oldest first."""
        return sorted(
            datetime.strptime(path.name, MONTH_FORMAT).date()
            for path in self.snapshots_dir.glob(MONTH_GLOB)
            if path.is_dir()
        )


@dataclass(frozen=True)
class Category:
    """A business category and the Lithuanian words Google Maps is searched for it with."""

    key: str
    keywords: tuple[str, ...]


CATEGORIES = (
    Category("cafes_bakeries", ("kavinė", "kepykla")),
    Category("car_repair", ("autoservisas",)),
    Category("dental_clinics", ("odontologijos klinika",)),
)
CITY = "Vilnius"
# A results list shows about 20 places, so the city is searched eldership by eldership.
ELDERSHIPS = (
    "Antakalnis",
    "Fabijoniškės",
    "Grigiškės",
    "Justiniškės",
    "Karoliniškės",
    "Lazdynai",
    "Naujamiestis",
    "Naujininkai",
    "Naujoji Vilnia",
    "Paneriai",
    "Pašilaičiai",
    "Pilaitė",
    "Rasos",
    "Senamiestis",
    "Šeškinė",
    "Šnipiškės",
    "Verkiai",
    "Vilkpėdė",
    "Viršuliškės",
    "Žirmūnai",
    "Žvėrynas",
)
RENDER_CAP = 200  # Oxylabs renders per collect run: 84 searches and their retries
