import hashlib
import json
from datetime import date

import duckdb
import pytest

from leads.collect import jar, vmi_taxes
from leads.collect.fetch import Fetcher, FetchError
from leads.collect.jar import Jar
from leads.collect.sodra import Sodra, header_codes, months_before
from leads.collect.source import RawFile
from leads.collect.vmi_taxes import VmiTaxes
from leads.config import Settings

ZIP = b"PK\x03\x04zip"


@pytest.fixture
def settings(tmp_path, raw_sources, month) -> Settings:
    """Return settings whose raw folders hold the fixture files for ``month``."""
    settings = Settings(tmp_path)
    raw_sources(month).write(settings)
    return settings


def snapshot(source, settings, month):
    """Snapshot ``source`` from its saved raw files; return columns, sorted rows and manifest."""
    out_dir = settings.root
    with Fetcher(offline=True) as fetcher, duckdb.connect() as con:
        files = source.fetch(fetcher, settings.raw_dir(source.name, month), month)
        source.snapshot(con, files, out_dir)
        rows = con.sql(f"SELECT * FROM '{out_dir / f'{source.name}.parquet'}' ORDER BY ALL")
        columns, values = rows.columns, rows.fetchall()
    manifest = json.loads((out_dir / f"{source.name}.json").read_text(encoding="utf-8"))
    return columns, values, manifest


def test_jar_snapshot_keeps_the_pulled_columns_and_quoted_names(settings, month):
    columns, rows, manifest = snapshot(Jar(), settings, month)
    assert columns == [
        "ja_kodas",
        "ja_pavadinimas",
        "adresas",
        "ja_reg_data",
        "form_kodas",
        "stat_kodas",
        "formavimo_data",
    ]
    assert rows[1][:3] == (
        "304000002",
        'Advokatų profesinė bendrija "LEGES | LB"',
        "Vilnius, Gedimino pr. 1, LT-01103",
    )
    assert (manifest["source"], manifest["rows"], manifest["period"]) == ("jar", 3, "2026-10-16")


def test_manifest_records_each_raw_file(settings, month):
    *_, manifest = snapshot(Jar(), settings, month)
    (file,) = manifest["files"]
    raw = settings.raw_dir("jar", month) / jar.FILE_NAME
    assert file["file"] == raw.name
    assert file["url"] == "https://www.registrucentras.lt/aduomenys/?byla=JAR_IREGISTRUOTI.csv"
    assert file["sha256"] == hashlib.sha256(raw.read_bytes()).hexdigest()
    assert file["fetched_at"].endswith("+00:00")


def test_snapshot_writes_an_lf_manifest_and_zstd_parquet(settings, month):
    snapshot(Jar(), settings, month)
    manifest = (settings.root / "jar.json").read_bytes()
    assert b"\r\n" not in manifest
    assert manifest.endswith(b"}\n")
    compression = duckdb.sql(
        f"SELECT DISTINCT compression FROM parquet_metadata('{settings.root / 'jar.parquet'}')"
    )
    assert compression.fetchall() == [("ZSTD",)]


def test_snapshot_fails_when_a_source_column_disappears(settings, month):
    raw = settings.raw_dir("jar", month) / jar.FILE_NAME
    raw.write_text(raw.read_text(encoding="utf-8").replace("stat_kodas", "statusas"), "utf-8")
    with pytest.raises(duckdb.BinderException, match="stat_kodas"):
        snapshot(Jar(), settings, month)


def test_sodra_snapshot_reads_both_header_layouts_by_column_code(tmp_path, raw_sources):
    month = date(2026, 3, 1)  # Sodra's latest three months span 2025 and 2026
    settings = Settings(tmp_path)
    raw_sources(month).write(settings)
    columns, rows, manifest = snapshot(Sodra(), settings, month)
    assert columns == ["jarCode", "month", "numInsured", "ecoActCode"]
    assert len(rows) == (12 + 1) * 3
    assert ("304000002", "202512", "1", "15000") in rows  # from the 2025 layout
    assert ("304000002", "202601", "1", "15000") in rows  # from the 2026 layout
    assert (None, "202601", "1", None) in rows
    assert [file["file"] for file in manifest["files"]] == [
        "monthly-2025.csv.zip",
        "monthly-2026.csv.zip",
    ]
    assert manifest["period"] == "202601"


def test_header_codes_come_from_the_last_brackets(tmp_path):
    csv = tmp_path / "monthly.csv"  # with a byte-order mark, as Sodra writes it
    header = "Mėnuo (month);Apdraustieji (visi) (numInsured);Savivaldybė(municipality)"
    csv.write_text(header + "\r\n", "utf-8-sig")
    assert header_codes(csv) == ["month", "numInsured", "municipality"]


def test_header_without_a_column_code_is_rejected(tmp_path):
    csv = tmp_path / "monthly.csv"
    csv.write_text("Mėnuo (month);Pavadinimas\n", encoding="utf-8")
    with pytest.raises(FetchError, match="'Pavadinimas'"):
        header_codes(csv)


@pytest.mark.parametrize(
    ("month", "years"),
    [
        (date(2026, 10, 1), [2026]),  # May to August
        (date(2027, 2, 1), [2026]),  # January 2027 is not published yet
        (date(2027, 3, 1), [2026, 2027]),
        (date(2027, 5, 1), [2026, 2027]),  # December 2026, if March 2027 is late
        (date(2027, 7, 1), [2027]),
    ],
)
def test_sodra_fetches_the_years_of_its_latest_three_months(session, tmp_path, month, years):
    for _ in years:
        session.reply(ZIP)
    with Fetcher(offline=False) as fetcher:
        files = Sodra().fetch(fetcher, tmp_path, month)
    assert [request.url for request in session.requests] == [
        f"https://atvira.sodra.lt/imones/downloads/{year}/monthly-{year}.csv.zip" for year in years
    ]
    assert [file.path.name for file in files] == [f"monthly-{year}.csv.zip" for year in years]


@pytest.mark.parametrize(
    ("month", "count", "expected"),
    [(date(2026, 10, 1), 2, date(2026, 8, 1)), (date(2027, 2, 1), 5, date(2026, 9, 1))],
)
def test_months_before_crosses_the_year(month, count, expected):
    assert months_before(month, count) == expected


def test_vmi_taxes_saves_every_page_of_three_years(session, tmp_path, month):
    session.reply(json.dumps({"_data": [{"metai": 2025}], "_page": {"next": "abc="}}).encode())
    session.reply(json.dumps({"_data": [{"metai": 2026}], "_page": {}}).encode())
    with Fetcher(offline=False) as fetcher:
        (file,) = VmiTaxes().fetch(fetcher, tmp_path, month)
    first, second = (request.url for request in session.requests)
    assert first.endswith(
        "?select(_page,mm_kodas.ja_kodas,pavadinimas,metai,menuo,suma,atnaujinta)"
        "&metai>=2024&limit(20000)"
    )
    assert second == first + '&page("abc=")'
    assert file.url == first
    lines = file.path.read_text(encoding="utf-8").splitlines()
    assert lines == ['{"metai": 2025}', '{"metai": 2026}']


def test_vmi_taxes_reuses_the_saved_file(session, tmp_path, month):
    (tmp_path / vmi_taxes.FILE_NAME).write_text("{}\n", encoding="utf-8")
    with Fetcher(offline=True) as fetcher:
        VmiTaxes().fetch(fetcher, tmp_path, month)
    assert session.requests == []


def test_vmi_taxes_snapshot_keeps_only_trade_names(settings, month):
    columns, rows, manifest = snapshot(VmiTaxes(), settings, month)
    assert columns == ["ja_kodas", "trade_name", "metai", "menuo", "suma", "atnaujinta"]
    updated = date(2026, 10, 8)
    assert rows == [
        (304000001, "Kavos namai", 2025, 12, 15000.5, updated),
        (304000001, "Kavos namai", 2026, 8, 9000.0, updated),
        (304000001, "Kavos namai", 2026, 9, 10000.25, updated),
        (304000003, None, 2025, 12, 81.94, updated),  # named after its owner only
        (304000004, "Saulės kepykla", 2025, 12, 4210.0, updated),
        (304000005, "Ratai", 2025, 12, 3100.0, updated),  # the last of nested quotes
        (304000006, None, 2025, 12, 950.0, updated),  # a trade name with an initial and a name
        (None, None, 2025, 12, 135653.74, updated),  # a foreign payer, without a company code
    ]
    assert (manifest["rows"], manifest["period"]) == (8, "2026-10-08")


@pytest.mark.parametrize(
    ("name", "trade_name"),
    [
        ('UAB "Kavos namai"', "Kavos namai"),
        ("Onos Onaitės IĮ „Saulės kepykla“", "Saulės kepykla"),
        ('IĮ "A. Petraičio firma "Ratai"', "Ratai"),  # nested quotes: the last part
        ('UAB "AB Sistemos"', "AB Sistemos"),
        ("Jono Jonaičio IĮ", None),
        ('IĮ "V. Petraičio įmonė"', None),
        ('IĮ "V.Jonaičio įmonė"', None),
        ('IĮ "Optika O. Onaitės"', None),
        ('IĮ "Onos Petraitienės kavinė"', None),
        ('IĮ "Jono Jonaičio autoservisas"', None),
        ('IĮ "Petro Kazlausko dirbtuvė"', None),
        ('IĮ "Dariaus Jankevičiaus įmonė"', None),
        ('IĮ "RASOS ONAITĖS ĮMONĖ"', None),
        ('IĮ "JONO PETRAIČIO ĮMONĖ"', None),
        ('IĮ "ONOS PETRAITIENĖS KIRPYKLA"', None),
        ('IĮ "Jonas Petrauskas"', None),
        ('IĮ "Ona Onaitytė"', None),
        ('IĮ "RASA PETRAITIENĖ"', None),
        ('IĮ "Eglė Jonaitė"', None),
        ('IĮ "Rasa Petrūtė"', None),
        ('IĮ "Ona Bernotutė"', None),
        ('IĮ "Kęstutis Petraitis"', None),
        ('IĮ "Kazys Jonėnas"', None),
        ('IĮ "Matas Petronis"', None),
        ('IĮ "Linas Jonūnas"', None),
        ('IĮ "Andrius Petrevičius"', None),
        ('IĮ "Tomas Jonickas"', None),
        ('IĮ "Petras Jonaitinskas"', None),
        ('IĮ "Gera Duonaitėlė"', "Gera Duonaitėlė"),  # a surname's suffix inside a longer word
        ('IĮ "Raudonas Dviratis"', "Raudonas Dviratis"),  # nominative, no surname's suffix
        ('IĮ "MANO GĖLĖS"', "MANO GĖLĖS"),  # in capitals, common endings are not a name
        ('IĮ "Senamiesčio kepykla"', "Senamiesčio kepykla"),
    ],
)
def test_vmi_taxes_keeps_a_trade_name_without_an_owner_s_name(tmp_path, name, trade_name):
    raw = tmp_path / vmi_taxes.FILE_NAME
    payer = {"mm_kodas": None, "pavadinimas": name, "metai": 2025, "menuo": 12, "suma": 1.0}
    raw.write_text(json.dumps(payer | {"atnaujinta": "2026-10-08"}) + "\n", encoding="utf-8")
    files = [RawFile("https://example.lt", raw)]
    with duckdb.connect() as con, VmiTaxes().rows(con, files) as rows:
        assert rows.select("trade_name").fetchall() == [(trade_name,)]
