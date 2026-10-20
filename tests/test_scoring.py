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


# Holds and peer groups, on company facts written by hand

SUBJECT = 304100001


def fact(
    code: int,
    *,
    category: str = "cafes_bakeries",
    places: int = 1,
    reviews: int = 100,
    closed: bool = False,
    owner_operated: bool = False,
    reg_date: str = "2018-01-01",
    tax: str | None = "10000",
) -> str:
    """Return a row of mart.company_facts for the fixture month, with 2025 as the tax year."""
    return (
        f"({MONTH}, {code}, '{category}', {places}, {reviews}, {closed}, {owner_operated}, "
        f"DATE '{reg_date}', 2.0, 2025, {tax or 'NULL'})"
    )


def peers(count: int, **details: object) -> list[str]:
    return [fact(304200000 + number, reviews=100 + number, **details) for number in range(count)]


def scores(stg_run, *facts: str) -> dict[int, tuple]:
    """Score ``facts`` alone; return each company's hold, peer group and peers."""
    stg_run.build_int()
    stg_run.warehouse.run_layer(stg_run.run, "mart")
    stg_run.warehouse.con.execute(
        f"DELETE FROM mart.company_facts; INSERT INTO mart.company_facts VALUES {', '.join(facts)}"
    )
    stg_run.warehouse.execute_file(stg_run.warehouse.sql_dir / "mart" / "40_scores.sql")
    rows = stg_run.rows("SELECT ja_kodas, hold_reason, peer_group, peers FROM mart.scores")
    return {code: tuple(score) for code, *score in rows}


@pytest.mark.parametrize(
    ("details", "hold"),
    [
        ({"closed": True}, "closed"),
        ({"reg_date": "2025-02-01"}, "young"),  # registered after January of the tax year
        ({"reg_date": "2025-01-31"}, None),
        ({"tax": None}, "no_tax_record"),
        ({"closed": True, "reg_date": "2025-02-01", "tax": None}, "closed"),
        ({"reg_date": "2025-02-01", "tax": None}, "young"),
    ],
    ids=["closed", "young", "january", "no-tax-record", "closed-first", "young-before-tax"],
)
def test_a_company_the_data_cannot_judge_is_held(stg_run, details, hold):
    held = scores(stg_run, fact(SUBJECT, **details), *peers(5))[SUBJECT]
    assert held == ((hold, None, None) if hold else (None, "category", 5))


@pytest.mark.parametrize(("count", "hold"), [(4, "few_peers"), (5, None)])
def test_a_company_with_fewer_than_five_peers_is_held(stg_run, count, hold):
    assert scores(stg_run, fact(SUBJECT), *peers(count))[SUBJECT] == (hold, "category", count)


def test_peers_run_one_place_in_the_category_and_legal_form_group_and_are_not_closed(stg_run):
    others = [
        fact(304300001, places=2),
        fact(304300002, category="car_repair"),
        fact(304300003, owner_operated=True),
        fact(304300004, closed=True),
    ]
    scored = scores(stg_run, fact(SUBJECT, places=3), *peers(5), *others)
    assert scored[SUBJECT] == (None, "category", 5)  # the five, not the others
    assert scored[304300002] == ("few_peers", "category", 0)  # the only car repair company


@pytest.mark.parametrize(
    ("count", "group", "group_peers"),
    [(26, "review tercile", 8), (23, "category", 23)],  # terciles of 9, or of 8
)
def test_the_review_tercile_is_the_peer_group_when_it_holds_eight_peers(
    stg_run, count, group, group_peers
):
    dentists = [fact(304500000 + n, category="dental_clinics", reviews=n) for n in range(27)]
    score = scores(stg_run, fact(SUBJECT, reviews=1), *peers(count), *dentists)[SUBJECT]
    assert score == (None, group, group_peers)  # terciles are the category's own


def test_the_review_terciles_go_by_reviews(stg_run):
    # the busiest company, numbered first: by number it would share its tercile with the nine
    # quietest, which run two places each and so are no one's peers
    quietest = [fact(304200000 + number, places=2, reviews=number) for number in range(9)]
    busier = [fact(304200009 + number, reviews=100 + number) for number in range(20)]
    score = scores(stg_run, fact(304000001, reviews=1000), *quietest, *busier)[304000001]
    assert score == (None, "review tercile", 9)


def test_a_rerun_scores_each_company_once_and_a_repeat_stops_the_build(stg_run):
    scores(stg_run, fact(SUBJECT))
    stg_run.warehouse.execute_file(stg_run.warehouse.sql_dir / "mart" / "40_scores.sql")
    assert stg_run.rows("SELECT count(*) FROM mart.scores") == [(1,)]
    stg_run.warehouse.con.execute("INSERT INTO mart.scores SELECT * FROM mart.scores")
    with pytest.raises(DataQualityError, match="mart_unique_keys"):
        stg_run.warehouse.run_checks(stg_run.run, "mart")
