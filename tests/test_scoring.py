from datetime import date
from decimal import Decimal

import pytest

from leads.checks import DataQualityError

MONTH = "getvariable('snapshot_month')"
COZY_BUILDING = "Vilnius, Dominikonų g. 10-3, LT-01120"  # the building of the place Cozy
UAB, MB = 310, 960


def employer(
    code: int,
    name: str,
    legal_form: int = UAB,
    insured: tuple[int, ...] = (),
    tax: str | None = None,
    address: str = COZY_BUILDING,
) -> list[str]:
    """Return SQL registering an active company, with ``insured`` people in Sodra's latest months,
    the newest first, and its VMI tax for 2025."""
    sql = [
        f"INSERT INTO stg.jar_entities VALUES ({MONTH}, {code}, '{name}', '{address}', "
        f"DATE '2018-01-01', {legal_form}, 0)"
    ]
    sql += [
        f"INSERT INTO stg.sodra_monthly VALUES "
        f"({MONTH}, {code}, DATE '2026-08-01' - INTERVAL {back} MONTH, {people}, '561100')"
        for back, people in enumerate(insured)
    ]
    if tax is not None:
        sql.append(f"INSERT INTO stg.vmi_taxes VALUES ({MONTH}, {code}, NULL, 2025, 12, {tax})")
    return sql


def facts(stg_run, *changes: str) -> dict[int, tuple]:
    """Build the int and mart layers after ``changes``; return each company's facts."""
    stg_run.build_int(*changes)
    stg_run.warehouse.run_layer(stg_run.run, "mart")
    rows = stg_run.rows(
        "SELECT ja_kodas, category, places, reviews, closed, owner_operated, reg_date, "
        "insured_3m, tax_year, tax FROM mart.company_facts"
    )
    return {code: tuple(fact) for code, *fact in rows}


@pytest.mark.parametrize(("legal_form", "owner_operated"), [(UAB, False), (MB, True)])
def test_a_linked_company_s_reviews_staff_and_tax(stg_run, legal_form, owner_operated):
    assert facts(
        stg_run, *employer(304100001, 'UAB "Cozy"', legal_form, (4, 3, 2, 9), "15000.50")
    ) == {
        304100001: (
            "cafes_bakeries",
            1,
            1815,
            True,  # the fixture month has Cozy closed
            owner_operated,
            date(2018, 1, 1),
            3.0,  # August to June; May's 9 is older than Sodra's latest three months
            2025,
            Decimal("15000.50"),
        )
    }


def test_a_company_without_sodra_or_vmi_rows_has_no_staff_and_no_known_tax(stg_run):
    (fact,) = facts(stg_run, *employer(304100001, 'UAB "Cozy"')).values()
    assert fact[-3:] == (0.0, 2025, None)  # insured, tax year, tax


def test_the_tax_is_of_the_latest_full_year(stg_run):
    (fact,) = facts(
        stg_run,
        *employer(304100001, 'UAB "Cozy"', tax="15000.50"),
        f"INSERT INTO stg.vmi_taxes VALUES ({MONTH}, 304100001, NULL, 2026, 9, 20000)",
    ).values()
    assert fact[-2:] == (2025, Decimal("15000.50"))


def test_a_tax_year_s_row_short_of_twelve_months_is_no_known_tax(stg_run):
    (fact,) = facts(
        stg_run,
        *employer(304100001, 'UAB "Cozy"'),
        f"INSERT INTO stg.vmi_taxes VALUES ({MONTH}, 304100001, NULL, 2025, 11, 14000)",
    ).values()
    assert fact[-2:] == (2025, None)


def test_a_company_s_places_add_up_under_its_busiest_place_s_category(stg_run):
    (fact,) = facts(
        stg_run,
        # Užupio kavinė becomes a car repair shop of the brand, open, with 2263 reviews
        "UPDATE stg.google_listings SET name = 'Cozy', category = 'car_repair', "
        "google_category = 'Automobilių servisas' WHERE name = 'Užupio kavinė'",
        # registered in its building; a café's activity links it to the café Cozy by brand
        *employer(304100001, 'UAB "Cozy"', insured=(1,), address="Vilnius, Užupio g. 2"),
    ).values()
    assert fact[:4] == ("car_repair", 2, 1815 + 2263, False)  # closed only when both are


@pytest.mark.parametrize(
    "changes",
    [
        employer(304100001, 'MB "Rytas"', insured=(1,)),  # the only fitting company: review
        [
            *employer(304100001, 'UAB "Cozy"'),
            f"INSERT INTO stg.match_labels SELECT {MONTH}, cid, 304100001, 'random', false "
            "FROM stg.google_listings WHERE name = 'Cozy'",
        ],
    ],
    ids=["review", "rejected"],
)
def test_only_a_company_with_an_automatic_link_has_facts(stg_run, changes):
    assert facts(stg_run, *changes) == {}


def test_a_repeated_company_stops_the_build(stg_run):
    facts(stg_run, *employer(304100001, 'UAB "Cozy"'))
    stg_run.warehouse.con.execute("INSERT INTO mart.company_facts SELECT * FROM mart.company_facts")
    with pytest.raises(DataQualityError, match="mart_unique_keys"):
        stg_run.warehouse.run_checks(stg_run.run, "mart")
