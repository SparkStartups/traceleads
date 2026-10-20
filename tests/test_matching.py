from contextlib import nullcontext

import pytest

from leads.checks import DataQualityError
from leads.config import Settings

MONTH = "getvariable('snapshot_month')"


def company(code: int, name: str, address: str, *activities: str) -> str:
    """Return SQL registering an active UAB, with Sodra activity codes for its last months."""
    sodra = "".join(
        f"INSERT INTO stg.sodra_monthly VALUES "
        f"({MONTH}, {code}, DATE '2026-08-01' - INTERVAL {months_back} MONTH, 3, '{activity}');"
        for months_back, activity in enumerate(reversed(activities))
    )
    jar = (
        f"INSERT INTO stg.jar_entities VALUES "
        f"({MONTH}, {code}, '{name}', '{address}', DATE '2018-01-01', 310, 0);"
    )
    return jar + sodra


def candidates(stg_run) -> dict[str, tuple]:
    """Return the evidence of each candidate pair, by the company's name."""
    pairs = stg_run.rows(
        "SELECT companies.name, same_brand, same_core, same_building, same_street, "
        "shared_words, fitting_activity "
        "FROM int.candidates JOIN int.companies USING (snapshot_month, ja_kodas)",
    )
    return {name: tuple(evidence) for name, *evidence in pairs}


COZY_BUILDING = "Vilnius, Dominikonų g. 10-3, LT-01120"
COZY_STREET = "Vilnius, Dominikonų g. 3, LT-01120"


def test_a_company_of_the_brand_in_the_place_s_building_shares_all_evidence(stg_run):
    stg_run.build_int(company(304100001, 'UAB "Cozy"', COZY_BUILDING, "561100"))
    assert candidates(stg_run) == {'UAB "Cozy"': (True, True, True, True, ["cozy"], True)}


def test_a_company_of_the_brand_elsewhere_shares_the_brand_and_its_activity(stg_run):
    address = "Kaunas, Laisvės al. 5, LT-44001"
    stg_run.build_int(company(304100001, 'UAB "Cozy"', address, "107100"))
    assert candidates(stg_run) == {'UAB "Cozy"': (True, True, False, False, ["cozy"], True)}


def test_the_brand_alone_makes_a_candidate(stg_run):
    stg_run.build_int(
        "UPDATE stg.google_listings SET name = 'Go' WHERE name = 'Cozy'",
        company(304100001, 'UAB "Go"', "Kaunas, Laisvės al. 5, LT-44001"),
    )
    assert candidates(stg_run) == {'UAB "Go"': (True, True, False, False, [], False)}


def test_another_company_in_the_building_shares_only_the_building(stg_run):
    stg_run.build_int(company(304100001, 'MB "Rytas"', COZY_BUILDING, "862300"))
    assert candidates(stg_run) == {
        'MB "Rytas"': (False, False, True, True, [], False)  # a dentist's activity
    }


def test_the_latest_activity_code_decides(stg_run):
    stg_run.build_int(company(304100001, 'UAB "Cozy"', COZY_BUILDING, "561100", "862300"))
    assert candidates(stg_run)['UAB "Cozy"'][-1] is False  # a café until July, a dentist now


@pytest.mark.parametrize(("others", "kept"), [(29, True), (30, False)])
def test_a_shared_word_on_the_street_counts_while_30_company_names_at_most_use_it(
    stg_run, others, kept
):
    stg_run.build_int(
        "UPDATE stg.google_listings SET name = 'Kavinė Cozy Garden' WHERE name = 'Cozy'",
        company(304100001, 'UAB "Garden Fox"', COZY_STREET),
        f"INSERT INTO stg.jar_entities SELECT {MONTH}, 304200000 + i, 'UAB \"Garden ' || i || "
        f"'\"', 'Kaunas, Laisvės al. 1, LT-44001', DATE '2018-01-01', 310, 0 "
        f"FROM range({others}) AS numbers(i)",
    )
    garden_fox = (False, False, False, True, ["garden"], False)
    assert candidates(stg_run) == ({'UAB "Garden Fox"': garden_fox} if kept else {})


def test_a_shared_word_of_three_letters_counts(stg_run):
    stg_run.build_int(
        "UPDATE stg.google_listings SET name = 'Kavinė Cozy Fox' WHERE name = 'Cozy'",
        company(304100001, 'UAB "Fox Den"', COZY_STREET),
    )
    assert candidates(stg_run) == {'UAB "Fox Den"': (False, False, False, True, ["fox"], False)}


def test_a_place_without_a_street_still_shares_its_words(stg_run):
    stg_run.build_int(
        "UPDATE stg.google_listings SET address = 'Vilnius' WHERE name = 'Cozy'",
        company(304100001, 'UAB "Cozy"', "Kaunas, Laisvės al. 5, LT-44001"),
    )
    assert candidates(stg_run) == {'UAB "Cozy"': (True, True, False, False, ["cozy"], False)}


@pytest.mark.parametrize(
    ("place", "name", "address"),
    [
        ("Cozy", 'UAB "Zeta"', COZY_STREET),  # the street alone
        ("Užupio kavinė", 'UAB "Užupio menai"', "Vilnius, Užupio g. 30, LT-01200"),  # its name
        ("Kavinė Cozy Go", 'UAB "Go Fox"', COZY_STREET),  # a word of two letters
        ("Kavinė Cozy 365", 'UAB "365 Fox"', COZY_STREET),  # a number
        ("Cozy", 'UAB "Senamiestis"', "Telšiai, Turgaus a. 11, LT-87101"),  # a place out of scope
    ],
    ids=["street", "street-name", "short-word", "number", "out-of-scope"],
)
def test_a_pair_without_evidence_is_no_candidate(stg_run, place, name, address):
    stg_run.build_int(
        f"UPDATE stg.google_listings SET name = '{place}' WHERE name = 'Cozy'",
        company(304100001, name, address),
    )
    assert name not in candidates(stg_run)


def test_a_repeated_candidate_stops_the_build(stg_run):
    stg_run.build_int(company(304100001, 'UAB "Cozy"', COZY_BUILDING, "561100"))
    stg_run.warehouse.con.execute("INSERT INTO int.candidates SELECT * FROM int.candidates")
    with pytest.raises(DataQualityError, match="int_unique_keys"):
        stg_run.warehouse.run_checks(stg_run.run, "int")


# Links: the first rule a place's candidates meet decides

KAUNAS = "Kaunas, Laisvės al. 5, LT-44001"


def links(stg_run) -> dict[str, tuple]:
    """Return each place in scope's company, tier, deciding rule and candidates, by place."""
    found = stg_run.rows(
        "SELECT places.name, companies.name, links.tier, links.rule, links.candidates "
        "FROM int.links JOIN int.places USING (snapshot_month, cid) "
        "LEFT JOIN int.companies USING (snapshot_month, ja_kodas)"
    )
    return {place: tuple(link) for place, *link in found}


def register(companies: list[tuple[str, str, str]]) -> list[str]:
    """Return SQL registering each (name, address, activity code) as an active UAB."""
    return [company(304100001 + number, *details) for number, details in enumerate(companies)]


@pytest.mark.parametrize(
    ("place", "companies", "link"),
    [
        (
            "Cozy",
            [('UAB "Cozy"', COZY_BUILDING, "862300")],
            ('UAB "Cozy"', "automatic", "brand_and_building", 1),
        ),
        (
            "Cozy",
            [('UAB "Cozy"', KAUNAS, "561100")],
            ('UAB "Cozy"', "automatic", "brand_and_activity", 1),
        ),
        (
            "Cozy",
            [('UAB "Kavinė Cozy"', COZY_BUILDING, "862300")],
            ('UAB "Kavinė Cozy"', "automatic", "core_and_building", 1),
        ),
        (
            "Kavinė Cozy Garden",
            [('UAB "Garden Fox"', COZY_STREET, "862300")],
            ('UAB "Garden Fox"', "review", "rare_word_on_street", 1),
        ),
        (
            "Cozy",
            [('MB "Rytas"', COZY_BUILDING, "561100"), ('UAB "Zeta"', COZY_BUILDING, "862300")],
            ('MB "Rytas"', "review", "only_fitting_in_building", 1),  # Zeta does not fit
        ),
    ],
    ids=[
        "brand-and-building",
        "brand-and-activity",
        "core-and-building",
        "rare-word-on-street",
        "only-fitting-in-building",
    ],
)
def test_each_rule_links_a_place(stg_run, place, companies, link):
    stg_run.build_int(
        f"UPDATE stg.google_listings SET name = '{place}' WHERE name = 'Cozy'",
        *register(companies),
    )
    assert links(stg_run)[place] == link


@pytest.mark.parametrize(
    "companies",
    [
        [('UAB "Cozy"', KAUNAS, "862300")],  # the brand elsewhere, with another activity
        [('MB "Rytas"', COZY_BUILDING, "862300")],  # the building, with another activity
        [('MB "Rytas"', COZY_BUILDING, "561100"), ('MB "Aušra"', COZY_BUILDING, "107100")],
        [],
    ],
    ids=["brand-elsewhere", "building", "two-fitting-in-building", "no-candidate"],
)
def test_a_place_that_meets_no_rule_is_unmatched(stg_run, companies):
    stg_run.build_int(*register(companies))
    assert links(stg_run)["Cozy"] == (None, "unmatched", None, 0)


@pytest.mark.parametrize(
    ("place", "companies", "link"),
    [
        (
            "Cozy",
            [('UAB "Cozy"', COZY_BUILDING, "862300"), ('MB "Cozy"', KAUNAS, "561100")],
            ('UAB "Cozy"', "automatic", "brand_and_building", 1),
        ),
        (
            "Cozy",
            [('UAB "Cozy"', KAUNAS, "561100"), ('UAB "Kavinė Cozy"', COZY_BUILDING, "862300")],
            ('UAB "Cozy"', "automatic", "brand_and_activity", 1),
        ),
        (
            "Kavinė Cozy Garden",
            [
                ('UAB "Cozy Garden"', COZY_BUILDING, "862300"),
                ('UAB "Garden Fox"', COZY_STREET, "862300"),
            ],
            ('UAB "Cozy Garden"', "automatic", "core_and_building", 1),
        ),
        (
            "Kavinė Cozy Garden",
            [('UAB "Garden Fox"', COZY_STREET, "862300"), ('MB "Rytas"', COZY_BUILDING, "561100")],
            ('UAB "Garden Fox"', "review", "rare_word_on_street", 1),
        ),
    ],
    ids=["1-before-2", "2-before-3", "3-before-4", "4-before-5"],
)
def test_the_first_rule_met_decides(stg_run, place, companies, link):
    stg_run.build_int(
        f"UPDATE stg.google_listings SET name = '{place}' WHERE name = 'Cozy'",
        *register(companies),
    )
    assert links(stg_run)[place] == link


def test_another_month_s_candidates_do_not_decide(stg_run):
    stg_run.build_int(*register([('UAB "Cozy"', KAUNAS, "561100")]))
    stg_run.build_int(
        "INSERT INTO int.candidates SELECT * REPLACE (snapshot_month - INTERVAL 1 MONTH AS "
        "snapshot_month) FROM int.candidates"
    )
    assert links(stg_run)["Cozy"] == ('UAB "Cozy"', "automatic", "brand_and_activity", 1)


def test_two_companies_under_the_deciding_rule_send_the_place_to_review(stg_run):
    stg_run.build_int(
        company(304100001, 'UAB "Cozy"', KAUNAS, "561100"),
        company(304100002, 'MB "Cozy"', KAUNAS, "107100"),
    )
    assert links(stg_run)["Cozy"] == (None, "review", "brand_and_activity", 2)


def test_only_places_in_scope_are_linked(stg_run):
    stg_run.build_int()
    assert set(links(stg_run)) == {"Cozy", "Užupio kavinė"}


def test_the_review_queue_lists_the_deciding_rule_s_candidates(stg_run):
    stg_run.build_int(
        company(304100001, 'UAB "Cozy"', KAUNAS, "561100"),
        company(304100002, 'MB "Cozy"', KAUNAS, "107100"),
        company(304100003, 'MB "Rytas"', COZY_BUILDING, "561100"),  # rule 5, not deciding
        company(304100004, 'UAB "Užupio kavinė"', "Vilnius, Užupio g. 2, LT-01200", "561100"),
    )  # Užupio kavinė's automatic link needs no one
    stg_run.build_int(
        "INSERT INTO int.companies SELECT * REPLACE (snapshot_month - INTERVAL 1 MONTH AS "
        "snapshot_month) FROM int.companies"
    )  # another month's companies join no candidate
    stg_run.warehouse.run_layer(stg_run.run, "mart")
    assert stg_run.rows(
        "SELECT place, company, company_address, rule, candidates, activity_code "
        "FROM mart.review_queue ORDER BY company"
    ) == [
        ("Cozy", 'MB "Cozy"', KAUNAS, "brand_and_activity", 2, "107100"),
        ("Cozy", 'UAB "Cozy"', KAUNAS, "brand_and_activity", 2, "561100"),
    ]


KLAIPEDA = "Klaipėda, Tiltų g. 1, LT-91246"


@pytest.mark.parametrize(
    ("companies", "reported"),
    [
        ([('UAB "Cozy"', KAUNAS, "561100"), ('MB "Cozy"', KLAIPEDA, "620100")], 1),
        ([('UAB "Cozy"', KAUNAS, "561100")], 0),  # the brand is the link's own
        ([('UAB "Cozy"', COZY_BUILDING, "561100"), ('MB "Cozy"', KLAIPEDA, "620100")], 0),
    ],
    ids=["brand-and-activity", "brand-not-shared", "brand-and-building"],
)
def test_a_link_by_brand_and_activity_whose_brand_another_company_uses_is_reported(
    stg_run, companies, reported
):
    stg_run.build_int(*register(companies))
    assert links(stg_run)["Cozy"][:2] == ('UAB "Cozy"', "automatic")
    assert stg_run.run_checks("int")["int_shared_brands"] == ("warn", reported)


def test_a_repeated_link_stops_the_build(stg_run):
    stg_run.build_int()
    stg_run.warehouse.con.execute("INSERT INTO int.links SELECT * FROM int.links")
    with pytest.raises(DataQualityError, match="int_unique_keys"):
        stg_run.warehouse.run_checks(stg_run.run, "int")


# Hand labels and each rule's precision


def label(selection: str, ja_kodas: int, correct: bool, place: str = "Cozy") -> str:
    """Return SQL labelling the link of ``place`` to ``ja_kodas``."""
    cid = f"(SELECT cid FROM stg.google_listings WHERE name = '{place}')"
    return (
        f"INSERT INTO stg.match_labels VALUES ({MONTH}, {cid}, {ja_kodas}, '{selection}', "
        f"{correct})"
    )


def read_labels(stg_run, project_root, rows: str) -> None:
    """Write ``rows`` under the labels file's header and load the stg layer again."""
    path = Settings(project_root).labels_dir / "match_labels.csv"
    path.write_text(path.read_text(encoding="utf-8") + rows, encoding="utf-8")
    stg_run.warehouse.run_layer(stg_run.run, "stg")


def test_labels_are_read_and_rows_without_a_verdict_left_out(stg_run, project_root):
    read_labels(
        stg_run,
        project_root,
        "random,11,304000001,brand_and_building,Cozy,UAB Cozy,yes\n"
        " flagged ,22,304000002,brand_and_activity,Moss,UAB Moss, no \n"
        "random,33,304000003,brand_and_building,Grey,UAB Grey,\n",  # not labelled yet
    )
    assert stg_run.rows("SELECT cid, ja_kodas, selection, correct FROM stg.match_labels") == [
        (11, 304000001, "random", True),
        (22, 304000002, "flagged", False),
    ]


@pytest.mark.parametrize(
    "row",
    [
        "flagged,44,304000004,brand_and_building,Gabi,UAB Gabi,maybe\n",
        "sample,55,304000005,brand_and_building,Balzac,UAB Balzac,yes\n",
    ],
    ids=["label", "selection"],
)
def test_an_unreadable_label_stops_the_build(stg_run, project_root, row):
    read_labels(stg_run, project_root, row)
    with pytest.raises(DataQualityError, match="stg_match_labels"):
        stg_run.warehouse.run_checks(stg_run.run, "stg")


@pytest.mark.parametrize(
    ("second", "outcome"),
    [
        ("random", pytest.raises(DataQualityError, match="stg_unique_keys")),
        ("flagged", nullcontext()),
    ],
)
def test_a_link_is_labelled_once_per_selection(stg_run, second, outcome):
    stg_run.warehouse.con.execute(label("random", 304100001, True))
    stg_run.warehouse.con.execute(label(second, 304100001, True))
    with outcome:
        stg_run.warehouse.run_checks(stg_run.run, "stg")


@pytest.mark.parametrize(
    ("labels", "tier"),
    [
        ([], "automatic"),
        ([("random", True)], "automatic"),
        ([("random", False)], "rejected"),
        ([("random", True), ("flagged", False)], "rejected"),  # one wrong label is enough
    ],
)
def test_a_link_labelled_wrong_is_rejected(stg_run, labels, tier):
    stg_run.build_int(
        *register([('UAB "Cozy"', KAUNAS, "561100")]),
        *(label(selection, 304100001, correct) for selection, correct in labels),
    )
    assert links(stg_run)["Cozy"] == ('UAB "Cozy"', tier, "brand_and_activity", 1)


@pytest.mark.parametrize(("correct", "queued"), [(True, [("Kavinė Cozy Garden",)]), (False, [])])
def test_a_review_link_labelled_wrong_leaves_the_review_queue(stg_run, correct, queued):
    stg_run.build_int(
        "UPDATE stg.google_listings SET name = 'Kavinė Cozy Garden' WHERE name = 'Cozy'",
        *register([('UAB "Garden Fox"', COZY_STREET, "862300")]),
        label("random", 304100001, correct, "Kavinė Cozy Garden"),
    )
    stg_run.warehouse.run_layer(stg_run.run, "mart")
    assert stg_run.rows("SELECT place FROM mart.review_queue") == queued


@pytest.mark.parametrize(
    ("ja_kodas", "place"),
    [(304100002, "Cozy"), (304100001, "Užupio kavinė")],
    ids=["another-company", "another-place"],
)
def test_a_wrong_label_of_another_link_leaves_the_link(stg_run, ja_kodas, place):
    stg_run.build_int(
        *register([('UAB "Cozy"', KAUNAS, "561100")]),
        label("random", ja_kodas, False, place),
    )
    assert links(stg_run)["Cozy"][1] == "automatic"


def test_precision_counts_the_links_labelled_at_random_with_a_wilson_interval(stg_run):
    stg_run.build_int()
    for number in range(15):  # links of rule 1 to companies 1..15; the first 10 drawn at random
        stg_run.warehouse.con.execute(
            f"INSERT INTO int.links VALUES ({MONTH}, {number}, {number + 1}, 'automatic', "
            f"'brand_and_building', 1); "
            f"INSERT INTO stg.match_labels VALUES ({MONTH}, {number}, {number + 1}, "
            f"'{'random' if number < 10 else 'flagged'}', {number != 0})"
        )
    stg_run.warehouse.con.execute(
        # a place the rule sent to review with two candidates, and last month's labels
        f"INSERT INTO int.links VALUES ({MONTH}, 99, NULL, 'review', 'brand_and_building', 2); "
        f"INSERT INTO stg.match_labels SELECT * REPLACE ({MONTH} - INTERVAL 1 MONTH AS "
        "snapshot_month) FROM stg.match_labels"
    )
    stg_run.warehouse.run_layer(stg_run.run, "mart")
    assert stg_run.rows(
        "SELECT places, linked, labelled, correct, precision, precision_low, precision_high "
        f"FROM mart.match_precision WHERE rule = 'brand_and_building' AND snapshot_month = {MONTH}"
    ) == [(16, 15, 10, 9, 0.9, 0.6, 0.98)]


def test_a_label_whose_link_the_rules_no_longer_make_is_reported(stg_run):
    stg_run.build_int(label("random", 304100001, True))  # no company 304100001 runs Cozy
    assert stg_run.run_checks("int")["int_labels_current"] == ("warn", 1)
