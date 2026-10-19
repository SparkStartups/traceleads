"""Project paths and the snapshot month."""

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

MONTH_FORMAT = "%Y-%m"


@dataclass(frozen=True)
class Settings:
    """Filesystem layout relative to the project root, the working directory by default."""

    root: Path = field(default_factory=Path.cwd)

    @property
    def snapshots_dir(self) -> Path:
        return self.root / "data" / "snapshots"

    def snapshot_months(self) -> list[date]:
        """Return the months with a snapshot, oldest first."""
        return sorted(
            datetime.strptime(path.name, MONTH_FORMAT).date()
            for path in self.snapshots_dir.glob("????-??")
            if path.is_dir()
        )
