"""Project paths, the snapshot month, and the configuration the collectors and models read:
the categories, the city and the legal forms."""

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

    def leads_csv(self, month: date) -> Path:
        """Return the lead list ``month``'s build writes."""
        return self.root / "output" / f"{month:{MONTH_FORMAT}}" / "leads.csv"

    @property
    def labels_dir(self) -> Path:
        """Hand labels of links, read with every snapshot month."""
        return self.root / "data" / "labels"

    def snapshot_months(self) -> list[date]:
        """Return the months with a snapshot, oldest first."""
        return sorted(
            datetime.strptime(path.name, MONTH_FORMAT).date()
            for path in self.snapshots_dir.glob(MONTH_GLOB)
            if path.is_dir()
        )


@dataclass(frozen=True)
class Category:
    """A business category: the Lithuanian words Google Maps is searched for it with, the Google
    categories of the places that belong to it, the activity classes (EVRK) of the companies that
    run them, and an innocent explanation shown with each of those companies, if it has one."""

    key: str
    keywords: tuple[str, ...]
    google_categories: tuple[str, ...]
    activity_classes: tuple[str, ...]
    explanation: str | None = None


CATEGORIES = (
    Category(
        key="cafes_bakeries",
        keywords=("kavinė", "kepykla"),
        google_categories=(
            "Kavinė",
            "Kavos parduotuvė",
            "Kepykla",
            "Konditerijos kepyklėlė",
            "Konditerijos gaminiai",
            "Konditerijos parduotuvė",
            "Tortų parduotuvė",
            "Desertų parduotuvė",
            "Desertų restoranas",
            "Kepyklos gaminių didmenininkas",
        ),
        # restaurants and cafés, bread and fresh pastry, cakes, shops of bread and confectionery
        activity_classes=("56.11", "10.71", "10.72", "47.24"),
    ),
    Category(
        key="car_repair",
        keywords=("autoservisas",),
        google_categories=(
            "Automobilių servisas",
            "Automobilių remontas ir priežiūra",
            "Automobilių dirbtuvės",
            "Automobilių paslauga",
            "Automobilių dažymo paslaugos",
            "Autoelektrikų paslaugos",
            "Mechanikas",
            "Padangų remonto servisas",
            "Padangų servisas",
            "Ratų suvedimo paslaugų teikėjas",
        ),
        activity_classes=("95.31",),  # repair and maintenance of motor vehicles
    ),
    Category(
        key="dental_clinics",
        keywords=("odontologijos klinika",),
        google_categories=("Odontologijos klinika", "Stomatologas", "Gydytojas odontologas"),
        activity_classes=("86.23",),  # dental practice
        explanation="dentists often bill through their own companies",
    ),
)
CITY = "Vilnius"
CITY_IN_NAMES = ("Vilniaus", "Vilniuje")  # "Vilniaus odontologijos klinika", "... Vilniuje"
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


@dataclass(frozen=True)
class Bounds:
    """A box of latitudes and longitudes."""

    lat_min: float
    lat_max: float
    lng_min: float
    lng_max: float


# Vilnius city municipality; a search by eldership name also finds places in other cities.
CITY_BOUNDS = Bounds(lat_min=54.567, lat_max=54.832, lng_min=25.024, lng_max=25.481)


@dataclass(frozen=True)
class LegalForm:
    """A legal form of the register that runs businesses. The owners of an owner-operated one
    need not be on its payroll; the register hides the name of a company named after its owner."""

    code: int
    abbreviation: str
    name: str  # as the register spells it
    owner_operated: bool = False
    named_after_owner: bool = False


LEGAL_FORMS = (
    LegalForm(310, "UAB", "Uždaroji akcinė bendrovė"),
    LegalForm(960, "MB", "Mažoji bendrija", owner_operated=True),
    LegalForm(810, "IĮ", "Individuali įmonė", owner_operated=True, named_after_owner=True),
    LegalForm(570, "VšĮ", "Viešoji įstaiga"),
    LegalForm(320, "AB", "Akcinė bendrovė"),
)


def generic_words() -> list[str]:
    """Return the words that say what a business is or where, not which one: those of the city's
    name and of every category's keywords and Google categories."""
    phrases = [CITY, *CITY_IN_NAMES]
    for category in CATEGORIES:
        phrases += [*category.keywords, *category.google_categories]
    return [word for phrase in phrases for word in phrase.split()]


@dataclass(frozen=True)
class Matching:
    """When a word that a place's and a company's names share counts as evidence: few company
    names use it, and it is long enough to mean something."""

    rare_word_max_names: int
    rare_word_min_letters: int


MATCHING = Matching(rare_word_max_names=30, rare_word_min_letters=3)


@dataclass(frozen=True)
class Scoring:
    """How a company is judged. Its staff is the average insured over Sodra's latest
    ``staff_months`` months. It is compared with at least ``min_peers`` peers of its category
    and legal-form group, or held; with its review tercile's alone when that leaves at least
    ``min_tercile_peers``. It is busy with at least its category's median reviews and
    ``min_reviews``; a staff or tax gap is a figure at most ``gap_ratio`` of the peers' median.
    It carries an innocent explanation when registered in its tax year or at most ``young_months``
    months before it, or with nobody insured and tax under ``little_tax`` euros."""

    staff_months: int
    min_peers: int
    min_tercile_peers: int
    min_reviews: int
    gap_ratio: float
    young_months: int
    little_tax: int


SCORING = Scoring(
    staff_months=3,
    min_peers=5,
    min_tercile_peers=8,
    min_reviews=50,
    gap_ratio=1 / 3,
    young_months=12,
    little_tax=1000,
)


@dataclass(frozen=True)
class Sensitivity:
    """The limits an analyst might dispute, which the companies are judged again with: each gap
    ratio with each minimum of reviews."""

    gap_ratios: tuple[float, ...]
    min_reviews: tuple[int, ...]


SENSITIVITY = Sensitivity(
    gap_ratios=(1 / 2, SCORING.gap_ratio, 1 / 4), min_reviews=(25, SCORING.min_reviews, 100)
)
