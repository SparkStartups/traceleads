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
        "insured, tax_year, tax FROM mart.company_facts"
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
    insured: float = 2.0,
    tax: str | None = "10000",
) -> str:
    """Return a row of mart.company_facts for the fixture month, with 2025 as the tax year."""
    return (
        f"({MONTH}, {code}, '{category}', {places}, {reviews}, {closed}, {owner_operated}, "
        f"DATE '{reg_date}', {insured}, 2025, {tax or 'NULL'})"
    )


def peers(count: int, **details: object) -> list[str]:
    return [fact(304200000 + number, reviews=100 + number, **details) for number in range(count)]


def scores(
    stg_run, *facts: str, columns: str = "hold_reason, peer_group, peers"
) -> dict[int, tuple]:
    """Score ``facts`` alone; return each company's ``columns``."""
    stg_run.build_int()
    stg_run.warehouse.run_layer(stg_run.run, "mart")
    stg_run.warehouse.con.execute(
        f"DELETE FROM mart.company_facts; INSERT INTO mart.company_facts VALUES {', '.join(facts)}"
    )
    stg_run.warehouse.execute_file(stg_run.warehouse.sql_dir / "mart" / "40_scores.sql")
    rows = stg_run.rows(f"SELECT ja_kodas, {columns} FROM mart.scores")
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


# Busy, gaps and tiers: five peers declaring 3 insured and 30000 tax, with reviews 100 to 104

PEERS = peers(5, insured=3.0, tax="30000")


@pytest.mark.parametrize(
    ("reviews", "others", "busy"),
    [
        (
            103,
            [*PEERS, *[fact(304500000 + n, category="car_repair", reviews=500) for n in range(9)]],
            True,
        ),
        (103, [*PEERS, *[fact(304500000 + n, reviews=500, closed=True) for n in range(9)]], True),
        (101, PEERS, False),  # under the category's median of 101.5
        (50, [fact(304200000 + n, reviews=40) for n in range(5)], True),
        (49, [fact(304200000 + n, reviews=40) for n in range(5)], False),  # under 50
    ],
    ids=["other-category", "held", "under-median", "at-fifty", "under-fifty"],
)
def test_a_busy_company_has_the_category_s_median_reviews_and_at_least_fifty(
    stg_run, reviews, others, busy
):
    scored = scores(stg_run, fact(SUBJECT, reviews=reviews), *others, columns="busy")
    assert scored[SUBJECT] == (busy,)


@pytest.mark.parametrize(
    ("details", "others", "gaps"),
    [
        ({"insured": 1.0, "tax": "10000"}, PEERS, (True, True)),  # a third of 3 and of 30000
        ({"insured": 1.01, "tax": "10001"}, PEERS, (False, False)),
        (  # 1.5 of 3 with owners
            {"insured": 0.5, "owner_operated": True},
            peers(5, owner_operated=True, insured=2.0),
            (False, False),
        ),
        ({"insured": 0.0, "tax": "0"}, peers(5, insured=0.0, tax="0"), (False, False)),
    ],
    ids=["a-third", "over-a-third", "owner", "peers-declare-nothing"],
)
def test_a_gap_is_at_most_a_third_of_the_peers_median(stg_run, details, others, gaps):
    scored = scores(stg_run, fact(SUBJECT, **details), *others, columns="staff_gap, tax_gap")
    assert scored[SUBJECT] == gaps


@pytest.mark.parametrize(
    ("details", "tier"),
    [
        ({"reviews": 103, "insured": 0.0, "tax": "5000"}, "lead"),
        ({"reviews": 103, "insured": 0.0, "tax": "30000"}, "watch"),  # tax at the median
        ({"reviews": 103, "insured": 0.0, "tax": "30001"}, "not_flagged"),  # more tax
        ({"reviews": 103, "insured": 3.0, "tax": "5000"}, "watch"),  # staff at the median
        ({"reviews": 103, "insured": 4.0, "tax": "5000"}, "not_flagged"),  # more staff
        ({"reviews": 101, "insured": 0.0, "tax": "5000"}, "not_flagged"),  # not busy
        ({"reviews": 103, "insured": 0.0, "tax": None}, "held"),
    ],
)
def test_a_busy_company_with_both_gaps_is_a_lead_and_with_one_on_watch(stg_run, details, tier):
    assert scores(stg_run, fact(SUBJECT, **details), *PEERS, columns="tier")[SUBJECT] == (tier,)


def test_leads_come_first_then_watch_each_by_the_euro_gap_to_the_peers_tax(stg_run):
    flagged = [  # watch with the largest gap, then three leads, two with the same gap
        fact(304100001, reviews=104, insured=3.0, tax="1000"),
        fact(304100004, reviews=104, insured=0.0, tax="9000"),
        fact(304100002, reviews=104, insured=0.0, tax="9000"),
        fact(304100003, reviews=104, insured=0.0, tax="5000"),
    ]
    scored = scores(stg_run, *flagged, *PEERS, columns="tier, rank, tax_gap_eur")
    assert [scored[code] for code in (304100003, 304100002, 304100004, 304100001)] == [
        ("lead", 1, 25000.0),
        ("lead", 2, 21000.0),  # a tie goes by code
        ("lead", 3, 21000.0),
        ("watch", 4, 29000.0),
    ]
    assert {scored[code][:2] for code in scored if code >= 304200000} == {("not_flagged", None)}


def test_the_peers_medians_are_those_of_the_chosen_peers(stg_run):
    tercile = [fact(304200000 + n, reviews=n, insured=n, tax=str(1000 + 100 * n)) for n in range(9)]
    others = [fact(304300000 + n, reviews=100 + n, insured=9.0, tax="9000") for n in range(17)]
    score = scores(
        stg_run,
        fact(SUBJECT, reviews=5),
        *tercile,
        *others,
        columns="peer_group, peers, peer_median_staff, peer_median_tax",
    )[SUBJECT]
    assert score == ("review tercile", 8, 3.5, 1350.0)  # medians of the eight quietest


@pytest.mark.parametrize(
    ("breakage", "check"),
    [
        (  # a held company, not judged busy
            "UPDATE mart.scores SET tier = 'lead', hold_reason = NULL WHERE tier = 'held'",
            "mart_leads_busy_with_both_gaps",
        ),
        (  # a busy company with a staff gap only
            "UPDATE mart.scores SET tier = 'lead' WHERE tier = 'watch'",
            "mart_leads_busy_with_both_gaps",
        ),
        ("UPDATE mart.scores SET hold_reason = NULL", "mart_holds_have_a_reason"),
        ("UPDATE mart.scores SET tier = 'not_flagged'", "mart_holds_have_a_reason"),
    ],
)
def test_the_scores_checks_stop_the_build(stg_run, breakage, check):
    watch = fact(304100002, reviews=104, insured=0.0, tax="30000")
    scores(stg_run, fact(SUBJECT, closed=True), watch, *PEERS)
    stg_run.warehouse.con.execute(breakage)
    with pytest.raises(DataQualityError, match=check):
        stg_run.warehouse.run_checks(stg_run.run, "mart")


OWNER = "owner-operated: one owner counted; more may work off the payroll"
QUIET = "nobody insured and almost no tax: it may no longer run the place"


@pytest.mark.parametrize(
    ("details", "explanations"),
    [
        ({}, []),
        ({"owner_operated": True}, [OWNER]),
        ({"reg_date": "2024-01-01"}, ["registered in 2024-01, so 2025 was among its first years"]),
        ({"reg_date": "2023-12-31"}, []),  # over 12 months before the tax year
        ({"reg_date": "2025-12-31"}, ["registered in 2025-12, so 2025 was among its first years"]),
        ({"reg_date": "2026-01-01"}, []),  # after the tax year
        ({"places": 2}, ["runs 2 places; peers run one"]),
        ({"category": "dental_clinics"}, ["dentists often bill through their own companies"]),
        ({"insured": 0.0, "tax": "999.99"}, [QUIET]),
        ({"insured": 0.0, "tax": "1000"}, []),
        ({"insured": 0.0, "tax": None}, []),  # a missing VMI row is not almost no tax
        ({"insured": 0.33, "tax": "0"}, []),
        ({"owner_operated": True, "places": 3}, [OWNER, "runs 3 places; peers run one"]),
    ],
    ids=[
        "none",
        "owner",
        "young",
        "a-year-before",
        "in-the-tax-year",
        "after-the-tax-year",
        "places",
        "dental",
        "quiet",
        "quiet-at-1000",
        "quiet-no-tax-record",
        "someone-insured",
        "several",
    ],
)
def test_a_company_carries_the_innocent_explanations_its_data_makes_plausible(
    stg_run, details, explanations
):
    scored = scores(stg_run, fact(SUBJECT, **details), columns="explanations")
    assert scored[SUBJECT] == (explanations,)


# The category summary and the sensitivity grid


SUMMARY = (
    "SELECT category, places, outside_city, other_activity, in_scope, linked, in_review, rejected, "
    "unmatched, companies, held, judged, busy, leads, watch, flagged_share "
    "FROM mart.category_summary ORDER BY category"
)


REJECT_COZY = (
    f"INSERT INTO stg.match_labels SELECT {MONTH}, cid, 304100001, 'random', false "
    "FROM stg.google_listings WHERE name = 'Cozy'"
)


@pytest.mark.parametrize(
    ("labelled_wrong", "linked", "rejected"),
    [(False, 1, 0), (True, 0, 1)],
    ids=["linked", "rejected"],
)
def test_the_category_summary_follows_the_places_into_scope_and_links(
    stg_run, labelled_wrong, linked, rejected
):
    facts(
        stg_run,
        "UPDATE stg.google_listings SET google_category = 'Kavinė' WHERE name = 'Grey'",
        *employer(304100001, 'UAB "Cozy"', tax="15000"),
        *employer(304100002, 'MB "Rytas"', insured=(1,), address="Vilnius, Užupio g. 2, LT-01200"),
        *([REJECT_COZY] if labelled_wrong else []),
    )  # Grey is in scope with no candidate; Užupio kavinė's one fitting company goes to review
    companies = (linked, linked, 0, 0, 0, 0, None)
    assert stg_run.rows(SUMMARY) == [
        ("cafes_bakeries", 20, 2, 15, 3, linked, 1, rejected, 1, *companies)
    ]


def test_the_category_summary_counts_the_companies_by_tier_with_the_flagged_share(stg_run):
    scores(
        stg_run,
        fact(SUBJECT, reviews=103, insured=0.0, tax="5000"),  # a lead
        fact(304100002, reviews=104, insured=0.0, tax="30000"),  # on watch
        fact(304100003, reviews=104, insured=3.0, tax="5000"),  # on watch
        fact(304100004, closed=True),
        fact(304100005, category="car_repair", reviews=500),  # held, with no peers
        *PEERS,
    )
    assert stg_run.rows(SUMMARY) == [
        ("cafes_bakeries", 20, 2, 16, 2, 0, 0, 0, 2, 9, 1, 8, 5, 1, 2, 3 / 8),
        ("car_repair", 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, None),  # no place found
    ]


PEERS_AT_40 = [fact(304200000 + n, reviews=40, insured=3.0, tax="30000") for n in range(5)]
WITHIN_A_THIRD = ((0.5, 25), (0.5, 50), (0.33, 25), (0.33, 50))  # 60 reviews, ratios of 1/3


@pytest.mark.parametrize(
    ("insured", "tax", "cells", "counts"),
    [
        (1.0, "10000", WITHIN_A_THIRD, (1, 0, 1)),  # leads, watch, leads kept
        (1.2, "12000", WITHIN_A_THIRD[:2], (1, 0, 0)),  # ratios of 0.4
        (1.0, "30000", WITHIN_A_THIRD, (0, 1, 0)),  # tax at the peers' median
        (3.0, "10000", WITHIN_A_THIRD, (0, 1, 0)),  # staff at the peers' median
    ],
    ids=["lead", "lead-at-a-half", "staff-gap", "tax-gap"],
)
def test_the_sensitivity_grid_tiers_the_judged_companies_again_at_each_setting(
    stg_run, insured, tax, cells, counts
):
    held = [  # with two peers only, so its gaps count nowhere
        fact(304300000, category="car_repair", reviews=60, insured=0.0, tax="1000"),
        fact(304300001, category="car_repair", reviews=40, insured=3.0, tax="30000"),
        fact(304300002, category="car_repair", reviews=40, insured=3.0, tax="30000"),
    ]
    scores(stg_run, fact(SUBJECT, reviews=60, insured=insured, tax=tax), *PEERS_AT_40, *held)
    grid = stg_run.rows(
        "SELECT round(gap_ratio, 2), min_reviews, leads, watch, leads_kept FROM mart.sensitivity"
    )
    assert len(grid) == 9
    assert {(gap, minimum): tuple(found) for gap, minimum, *found in grid if any(found)} == {
        cell: counts for cell in cells
    }


# Month over month


def month_over_month(stg_run, previous: list[str], current: list[str]) -> dict[int, tuple]:
    """Score ``current`` in the fixture month and ``previous`` in the month before it; return each
    company's change, tiers, category and causes."""
    scores(stg_run, *current)
    con = stg_run.warehouse.con
    con.execute(
        "SET VARIABLE snapshot_month = (getvariable('snapshot_month') - INTERVAL 1 MONTH)::DATE"
    )
    con.execute(f"INSERT INTO mart.company_facts VALUES {', '.join(previous)}")
    stg_run.warehouse.execute_file(stg_run.warehouse.sql_dir / "mart" / "40_scores.sql")
    rows = stg_run.rows(
        "SELECT ja_kodas, change, previous_tier, tier, category, causes FROM mart.month_over_month"
    )
    return {code: tuple(row) for code, *row in rows}


def test_the_first_month_has_nothing_to_compare_with(stg_run):
    scores(stg_run, fact(SUBJECT), *PEERS)
    assert stg_run.rows("SELECT * FROM mart.month_over_month") == []


def test_month_over_month_tells_new_gone_re_tiered_and_unchanged_companies(stg_run):
    lead = {"reviews": 103, "insured": 0.0, "tax": "5000"}
    changed = month_over_month(
        stg_run,
        [fact(304100001, **lead), fact(304100002), fact(304100003), *PEERS],
        [fact(304100001), fact(304100002), fact(304100004, category="car_repair"), *PEERS],
    )
    assert {code: row[:4] for code, row in changed.items() if code < 304200000} == {
        304100001: ("tier changed", "lead", "not_flagged", "cafes_bakeries"),
        304100002: ("unchanged", "not_flagged", "not_flagged", "cafes_bakeries"),
        304100003: ("gone", "not_flagged", None, "cafes_bakeries"),
        304100004: ("new", None, "held", "car_repair"),
    }


@pytest.mark.parametrize(
    ("before", "now", "causes"),
    [
        (
            {"reviews": 40, "insured": 0.0, "tax": "5000"},
            {"reviews": 103, "insured": 0.0, "tax": "5000"},
            ["busy: 40 → 103 reviews, category median 101.5 → 102.5"],
        ),
        (
            {"reviews": 103, "insured": 0.0, "tax": "5000"},
            {"reviews": 40, "insured": 0.0, "tax": "5000"},
            ["no longer busy: 103 → 40 reviews, category median 102.5 → 101.5"],
        ),
        (
            {"reviews": 103, "insured": 0.04, "tax": "5000"},
            {"reviews": 103, "insured": 2.55, "tax": "30000"},
            ["staff 0.0 → 2.6, peers 3.0 → 3.0", "tax 5000 → 30000, peers 30000 → 30000"],
        ),
        (  # still a lead: figures that moved on the same tier are no cause
            {"reviews": 103, "insured": 0.0, "tax": "5000"},
            {"reviews": 103, "insured": 0.5, "tax": "6000"},
            [],
        ),
        (  # from watch: the staff crossed the peers' median, not the gap
            {"reviews": 103, "insured": 3.0, "tax": "5000"},
            {"reviews": 103, "insured": 3.1, "tax": "5000"},
            ["staff 3.0 → 3.1, peers 3.0 → 3.0"],
        ),
        (  # from watch: the tax crossed the peers' median, not the gap
            {"reviews": 103, "insured": 0.0, "tax": "30000"},
            {"reviews": 103, "insured": 0.0, "tax": "30001"},
            ["tax 30000 → 30001, peers 30000 → 30000"],
        ),
        (
            {"reviews": 103},
            {"reviews": 103, "category": "car_repair"},
            ["held: few_peers", "category cafes_bakeries → car_repair"],
        ),
        ({"closed": True}, {}, ["judged again"]),
        ({}, {"tax": None}, ["held: no_tax_record"]),
        (None, {"closed": True}, ["linked to a place this month"]),
        ({"closed": True}, None, ["no longer linked to a place"]),
    ],
    ids=[
        "busy",
        "no-longer-busy",
        "staff-and-tax",
        "same-tier",
        "staff-past-the-median",
        "tax-past-the-median",
        "category",
        "judged-again",
        "held",
        "new",
        "gone",
    ],
)
def test_month_over_month_tells_what_moved_a_company(stg_run, before, now, causes):
    changed = month_over_month(
        stg_run,
        [*([] if before is None else [fact(SUBJECT, **before)]), *PEERS],
        [*([] if now is None else [fact(SUBJECT, **now)]), *PEERS],
    )
    assert changed[SUBJECT][-1] == causes


# The lead list


def link(place: str, tier: str = "automatic") -> str:
    """Return SQL linking the fixture place ``place`` to the subject."""
    return (
        f"INSERT INTO int.links SELECT {MONTH}, cid, {SUBJECT}, '{tier}', 'brand_and_building', "
        f"1 FROM int.places WHERE name = '{place}'"
    )


LEAD = {"reviews": 103, "insured": 0.96, "tax": "5000"}


def lead_list(
    stg_run, *changes: str, view: str = "mart.leads", subject: dict[str, object] = LEAD
) -> list[tuple]:
    """Score ``subject`` among five peers, register it and link it to the fixture place Cozy,
    apply ``changes``, and return ``view``'s rows."""
    scores(stg_run, fact(SUBJECT, **subject), *PEERS)
    for change in (
        "INSERT INTO int.companies (snapshot_month, ja_kodas, name, address, legal_form, reg_date) "
        f"VALUES ({MONTH}, {SUBJECT}, 'UAB \"Cozy\"', '{COZY_BUILDING}', {UAB}, DATE '2018-01-01')",
        link("Cozy"),
        *changes,
    ):
        stg_run.warehouse.con.execute(change)
    return stg_run.rows(f"SELECT * EXCLUDE (snapshot_month) FROM {view}")


def test_a_flagged_company_is_listed_with_its_places_numbers_and_reason(stg_run):
    (row,) = lead_list(stg_run, link("Užupio kavinė", "review"))  # in review: not one of its places
    (cid, address) = stg_run.rows("SELECT cid, address FROM int.places WHERE name = 'Cozy'")[0]
    assert row == (
        1,
        "lead",
        SUBJECT,
        'UAB "Cozy"',
        COZY_BUILDING,
        "cafes_bakeries",
        103,
        102.5,
        f"Cozy, {address} https://www.google.com/maps?cid={cid}",
        1.0,
        3.0,
        0.32,
        2025,
        Decimal("5000.00"),
        30000.0,
        0.17,
        25000.0,
        "category",
        5,
        "103 reviews, category median 102.5; staff gap: 1.0 against the peers' 3.0 (32%); "
        "tax gap: 5000 € in 2025 against the peers' 30000 € (17%)",
        "",
    )


@pytest.mark.parametrize(
    ("subject", "reason"),
    [
        (
            {"reviews": 103, "insured": 3.0, "tax": "5000"},
            "staff 3.0 against the peers' 3.0 (100%); tax gap: 5000 €",
        ),
        (
            {"reviews": 103, "insured": 1.0, "tax": "30000"},
            "staff gap: 1.0 against the peers' 3.0 (33%); tax 30000 €",
        ),
    ],
    ids=["tax-gap", "staff-gap"],
)
def test_a_watched_company_s_reason_names_its_one_gap(stg_run, subject, reason):
    (row,) = lead_list(stg_run, subject=subject)
    assert row[1] == "watch"
    assert reason in row[19]


def test_a_reason_leaves_out_the_share_of_a_peers_median_of_0(stg_run):
    zero = (
        "UPDATE mart.scores SET peer_median_staff = 0, staff_ratio = NULL, staff_gap = false, "
        "peer_median_tax = 0, tax_ratio = NULL, tax_gap = false"
    )
    (row,) = lead_list(stg_run, zero)
    assert row[19].endswith(
        "; staff 1.0 against the peers' 0.0; tax 5000 € in 2025 against the peers' 0 €"
    )


def test_the_list_rounds_its_figures(stg_run):
    rounding = (
        "UPDATE mart.scores SET peer_median_staff = 3.04, peer_median_tax = 30000.004, "
        "tax_gap_eur = 25000.004"
    )
    (row,) = lead_list(stg_run, rounding)
    assert (row[10], row[14], row[16]) == (3.0, 30000.0, 25000.0)


def test_a_company_s_places_come_from_its_own_month(stg_run):
    last_month = "(snapshot_month - INTERVAL 1 MONTH)::DATE AS snapshot_month"
    (row,) = lead_list(
        stg_run,
        f"INSERT INTO int.places SELECT * REPLACE ({last_month}) FROM int.places",
        f"INSERT INTO int.links SELECT * REPLACE ({last_month}) FROM int.links",
    )
    assert row[8].count("https://") == 1


def test_a_company_s_places_are_listed_busiest_first(stg_run):
    (row,) = lead_list(
        stg_run, link("Užupio kavinė"), "UPDATE int.places SET review_count = 1 WHERE name = 'Cozy'"
    )
    assert [place.split(",")[0] for place in row[8].split("; ")] == ["Užupio kavinė", "Cozy"]


@pytest.mark.parametrize(
    ("tier", "listed"), [("lead", 1), ("watch", 1), ("not_flagged", 0), ("held", 0)]
)
def test_only_leads_and_watch_are_listed(stg_run, tier, listed):
    rows = lead_list(stg_run, f"UPDATE mart.scores SET tier = '{tier}'")
    assert len(rows) == listed


def test_an_ii_s_registered_address_is_withheld(stg_run):
    (row,) = lead_list(
        stg_run, f"UPDATE int.companies SET legal_form = 810 WHERE ja_kodas = {SUBJECT}"
    )
    assert row[3:5] == ('UAB "Cozy"', None)


@pytest.mark.parametrize(
    ("text", "quote"),
    [("=1+1", "'"), ("+1", "'"), ("-1", "'"), ("@SUM(1)", "'"), ("\t=1", "'"), ("\r=1", "'")]
    + [("Cozy - 1", "")],  # not at the start
)
def test_the_export_quotes_register_and_google_text_a_spreadsheet_would_run(stg_run, text, quote):
    changes = (
        f"UPDATE int.companies SET name = '{text}', address = '{text}' WHERE ja_kodas = {SUBJECT}",
        f"UPDATE int.places SET name = '{text}', address = NULL WHERE name = 'Cozy'",
    )
    (exported,) = lead_list(stg_run, *changes, view="mart.leads_export")
    (listed,) = stg_run.rows("SELECT * EXCLUDE (snapshot_month) FROM mart.leads")
    assert exported[3:5] == (f"{quote}{text}", f"{quote}{text}")
    assert exported[8].startswith(f"{quote}{text} https://")
    assert listed[3] == text  # the app shows the text as it is
