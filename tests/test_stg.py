from datetime import date
from decimal import Decimal

import pytest

from leads.checks import DataQualityError
from leads.collect import collect_month
from leads.config import Settings
from leads.tracking import Run
from leads.warehouse import Warehouse


def rows(warehouse: Warehouse, sql: str) -> list[tuple]:
    return warehouse.con.execute(sql).fetchall()


def test_jar_entities_are_typed(stg_run):
    warehouse, _ = stg_run
    entities = rows(warehouse, "SELECT * EXCLUDE (snapshot_month) FROM stg.jar_entities ORDER BY 1")
    kavos_namai = (304000001, 'UAB "Kavos namai"', "Vilnius, Trakų g. 8-5, LT-01132")
    leges_name = 'Advokatų profesinė bendrija "LEGES | LB"'  # a pipe inside quotes
    leges = (304000002, leges_name, "Vilnius, Gedimino pr. 1, LT-01103")
    individual = (304000003, "Individuali įmonė", "Kaunas, Laisvės al. 1, LT-44001")
    assert entities == [
        (*kavos_namai, date(2019, 5, 2), 310, 0),
        (*leges, date(2009, 9, 24), 840, 0),
        (*individual, date(2015, 1, 10), 810, 7),  # in liquidation
    ]


def test_sodra_drops_foreign_insurers_and_pads_activity_codes(stg_run):
    warehouse, _ = stg_run
    assert rows(warehouse, "SELECT count(*), count(DISTINCT ja_kodas) FROM stg.sodra_monthly") == [
        (2 * 8, 2)  # two employers with a company code, January to August
    ]
    assert rows(
        warehouse,
        "SELECT ja_kodas, insured, evrk FROM stg.sodra_monthly "
        "WHERE data_month = DATE '2026-08-01' ORDER BY 1",
    ) == [(304000001, 5, "561100"), (304000002, 1, "015000")]


def test_vmi_taxes_keep_the_latest_month_of_each_year(stg_run):
    warehouse, _ = stg_run
    assert rows(
        warehouse,
        "SELECT ja_kodas, trade_name, tax_year, months, amount FROM stg.vmi_taxes ORDER BY 1, 3",
    ) == [
        (304000001, "Kavos namai", 2025, 12, Decimal("15000.50")),
        (304000001, "Kavos namai", 2026, 9, Decimal("10000.25")),
        (304000003, None, 2025, 12, Decimal("81.94")),
        (304000004, "Saulės kepykla", 2025, 12, Decimal("4210.00")),
        (304000005, "Ratai", 2025, 12, Decimal("3100.00")),
        (304000006, None, 2025, 12, Decimal("950.00")),
    ]


def test_source_files_list_every_raw_file(stg_run):
    warehouse, _ = stg_run
    assert rows(
        warehouse,
        "SELECT source, file, snapshot_rows, period FROM stg.source_files "
        "WHERE source <> 'google_maps' ORDER BY 1, 2",
    ) == [
        ("jar", "JAR_IREGISTRUOTI.csv", 3, "2026-10-16"),
        ("sodra", "monthly-2026.csv.zip", 3 * 8, "202608"),
        ("vmi_taxes", "vmi_taxes.jsonl", 8, "2026-10-08"),
    ]
    assert rows(
        warehouse,
        "SELECT count(*), any_value(snapshot_rows) FROM stg.source_files "
        "WHERE source = 'google_maps'",
    ) == [(84, 20)]


def test_google_listings_keep_every_place_of_every_query(stg_run):
    warehouse, _ = stg_run
    assert rows(
        warehouse, "SELECT count(*), count(DISTINCT cid), any_value(query) FROM stg.google_listings"
    ) == [(20, 20, "kavinė Antakalnis Vilnius")]
    assert rows(
        warehouse,
        "SELECT name, category, google_category, address, review_count, closed, file "
        "FROM stg.google_listings WHERE cid = 5596741140976187341",
    ) == [
        (
            "Cozy",
            "cafes_bakeries",
            "Kavinė",
            "Dominikonų g. 10",
            1815,
            True,  # temporarily closed in the fixture month
            "kavine-antakalnis-vilnius.html",
        )
    ]


def dq_results(warehouse: Warehouse) -> dict[str, tuple[str, int]]:
    return {
        name: (severity, failing)
        for name, severity, failing in rows(
            warehouse, "SELECT check_name, severity, failing_rows FROM meta.dq_results"
        )
    }


def test_checks_pass_and_full_or_empty_lists_are_only_reported(stg_run):
    warehouse, run = stg_run
    warehouse.run_checks(run, "stg")
    assert dq_results(warehouse) == {
        "stg_company_codes": ("error", 0),
        "stg_google_queries": ("warn", 84),  # one full list, 83 pages without one
        "stg_sodra_fresh": ("error", 0),
        "stg_sources_have_rows": ("error", 0),
        "stg_unique_keys": ("error", 0),
    }


@pytest.mark.parametrize(
    ("breakage", "check"),
    [
        ("DELETE FROM stg.jar_entities", "stg_sources_have_rows"),
        ("DELETE FROM stg.sodra_monthly", "stg_sources_have_rows"),
        ("DELETE FROM stg.vmi_taxes", "stg_sources_have_rows"),
        ("DELETE FROM stg.google_listings", "stg_sources_have_rows"),
        (
            "INSERT INTO stg.source_files SELECT * FROM stg.source_files LIMIT 1",
            "stg_unique_keys",
        ),
        (
            "INSERT INTO stg.jar_entities SELECT * FROM stg.jar_entities LIMIT 1",
            "stg_unique_keys",
        ),
        (
            "INSERT INTO stg.sodra_monthly SELECT * FROM stg.sodra_monthly LIMIT 1",
            "stg_unique_keys",
        ),
        ("INSERT INTO stg.vmi_taxes SELECT * FROM stg.vmi_taxes LIMIT 1", "stg_unique_keys"),
        (
            "INSERT INTO stg.google_listings SELECT * FROM stg.google_listings LIMIT 1",
            "stg_unique_keys",
        ),
        ("UPDATE stg.jar_entities SET ja_kodas = 12345 WHERE status = 7", "stg_company_codes"),
        (
            "UPDATE stg.sodra_monthly SET ja_kodas = 12345 WHERE ja_kodas = 304000002",
            "stg_company_codes",
        ),
        (
            "UPDATE stg.vmi_taxes SET ja_kodas = 1234567890 WHERE ja_kodas = 304000003",
            "stg_company_codes",
        ),
        (  # June, four months before October
            "UPDATE stg.sodra_monthly SET data_month = data_month - INTERVAL 2 MONTH",
            "stg_sodra_fresh",
        ),
    ],
)
def test_checks_catch_broken_sources(stg_run, breakage, check):
    warehouse, run = stg_run
    warehouse.con.execute(breakage)
    with pytest.raises(DataQualityError, match=check):
        warehouse.run_checks(run, "stg")


def test_sodra_three_months_old_is_still_fresh(stg_run):
    warehouse, run = stg_run
    warehouse.con.execute("UPDATE stg.sodra_monthly SET data_month = data_month - INTERVAL 1 MONTH")
    warehouse.run_checks(run, "stg")  # July, three months before October
    assert dq_results(warehouse)["stg_sodra_fresh"] == ("error", 0)


def test_a_month_without_places_is_stopped_by_its_check(
    project_root, raw_sources, place_page, month
):
    settings = Settings(project_root)
    raw_sources(month).write(settings)
    for page in settings.raw_dir("google_maps", month).iterdir():
        page.write_text(place_page, encoding="utf-8")  # Google opened a single place every time
    collect_month(settings, month)
    with (
        Warehouse.open(
            project_root / "test.duckdb", settings.sql_dir, settings.snapshot_dir(month)
        ) as warehouse,
        Run.start(warehouse.con, month) as run,
    ):
        warehouse.run_layer(run, "stg")
        with pytest.raises(DataQualityError, match="stg_sources_have_rows"):
            warehouse.run_checks(run, "stg")
