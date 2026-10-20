import pytest

from leads.checks import DataQualityError

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
