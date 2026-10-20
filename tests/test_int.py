import re
from collections import Counter

import pytest

from leads.checks import DataQualityError
from leads.warehouse import Warehouse

# Word lists as the models pass them: the words of legal forms, and the words that say what a
# business is or where.
FORM_WORDS = ["uab", "uzdaroji", "akcine", "bendrove", "mb", "individuali", "imone"]
GENERIC_WORDS = ["kavine", "kepykla", "autoservisas", "odontologijos", "klinika", "vilniaus"]


def value(text_macros, expression: str, *params: object) -> object:
    return text_macros.execute(f"SELECT {expression}", list(params)).fetchone()[0]


@pytest.mark.parametrize(
    ("name", "brand"),
    [
        ('UAB "Kavos namai"', "kavos namai"),
        ("UAB „Kavos namai“", "kavos namai"),
        ("Kavinė „Saulė“", "saule"),  # curly quotes on a Google name
        ('Uždaroji akcinė bendrovė "JUMILA"', "jumila"),
        ('"RSE AUTO", UAB', "rse auto"),
        ('MB "Kepykla "Sodas"', "sodas"),  # nested quotes: the last part
        ('Advokatų profesinė bendrija "LEGES | LB"', "leges lb"),
        ("UAB Summit Alpha", "summit alpha"),
        ("Kavinė Cozy", "kavine cozy"),  # a Google name goes through the same steps
        ("Individuali įmonė", None),  # the register's name for every IĮ
        ('UAB "UAB"', None),
    ],
)
def test_brand_key_is_the_quoted_name_without_legal_forms(text_macros, name, brand):
    assert value(text_macros, "int.brand_key(?, ?)", name, FORM_WORDS) == brand


@pytest.mark.parametrize(
    ("brand", "core"),
    [
        ("kavine cozy", "cozy"),
        ("cozy", "cozy"),
        ("autoservisas rimas", "rimas"),
        ("vilniaus odontologijos klinika", None),
        ("kepykla", None),
    ],
)
def test_core_key_drops_generic_words(text_macros, brand, core):
    assert value(text_macros, "int.core_key(?, ?)", brand, GENERIC_WORDS) == core


@pytest.mark.parametrize(
    ("address", "street", "house"),
    [
        ("Vilnius, Trakų g. 8-5, LT-01132", "traku", "8"),
        ("S. Žukausko g. 39", "zukausko", "39"),
        ("77 Vėtrungių gatvė", "vetrungiu", "77"),
        ("Verkių g. 31A", "verkiu", "31a"),
        ("Laisvės pr. 31", "laisves", "31"),
        ("Naujoji Riovonių g. 25C", "naujoji riovoniu", "25c"),
        ("Vilniaus g. 5", "vilniaus", "5"),  # a street named after the city
        ("Vilnius, Sausio 13-osios g. 11-38, LT-04345", "sausio osios", "11"),
        ("Vilnius, Loretos Asanavičiūtės g. 8-299, LT-04302", "loretos asanaviciutes", "8"),
        ("PC CUP, Upės g. 9", "upes", "9"),
        ("Halės Turgus | 1A paviljonas, Pylimo g. 58", "pylimo", "58"),
        ("PC Panorama | Saltoniškių g. 9", "saltoniskiu", "9"),
        ("P. Vileišio g. 18-8 korpusas", "vileisio", "18"),
        ("A. Mickevičiaus g. 64, Papiškės", "mickeviciaus", "64"),
        ("J. Matulaičio a. 5", "matulaicio", "5"),
        ("V. A. Graičiūno g. 2", "graiciuno", "2"),
        ("Šv. Ignoto g. 4", "sv ignoto", "4"),
        ("Taikos g. 104-54 Rygos g. kampas", "taikos", "104"),
        ("Gedimino pr. 9, Vilniaus g. 2", "gedimino", "9"),
        ("Kalvarijų 125-5korpusas", "kalvariju", "125"),  # without a street type
        ("Popieriaus g.", "popieriaus", None),
        ("Vilnius, Katedros a.", "katedros", None),  # a square
        ("Vilnius, LT-01132", None, None),
        ("Vilnius", None, None),
        ("M564+9JV", None, None),  # a plus code
    ],
)
def test_street_key_and_house_number(text_macros, address, street, house):
    keys = text_macros.execute("SELECT int.street_key(?), int.house_number(?)", [address] * 2)
    assert keys.fetchone() == (street, house)


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("traku", "traku", True),
        ("loretos asanaviciutes", "asanaviciutes", True),
        ("asanaviciutes", "loretos asanaviciutes", True),
        ("kozo", "ozo", False),  # only on a word boundary
        ("seskines sodu", "seskines", False),
        (None, "traku", None),
    ],
)
def test_same_street_allows_a_spelled_out_first_name(text_macros, a, b, same):
    assert value(text_macros, "int.same_street(?::VARCHAR, ?::VARCHAR)", a, b) is same


def test_empty_keys_never_match(text_macros):
    empty = "int.brand_key('UAB', ?) = int.brand_key('MB', ?)"
    assert value(text_macros, empty, FORM_WORDS, FORM_WORDS) is None
    assert value(text_macros, "int.plain_text(' - ')") is None


# The companies and places models, on the fixture month


def build_int(stg_run, *changes: str) -> Warehouse:
    """Apply ``changes`` to the fixture month's stg tables, then build the int layer."""
    warehouse, run = stg_run
    for change in changes:
        warehouse.con.execute(change)
    warehouse.run_layer(run, "int")
    return warehouse


def rows(warehouse: Warehouse, sql: str) -> list[tuple]:
    return warehouse.con.execute(sql).fetchall()


def test_key_words_are_the_configured_words_as_plain_text(stg_run):
    warehouse = build_int(stg_run)
    ((forms, generic),) = rows(warehouse, "SELECT form_words, generic_words FROM int.key_words")
    assert {"uab", "uzdaroji", "ii", "vsi"} <= set(forms)
    assert {"vilnius", "vilniaus", "vilniuje", "kavine", "automobiliu"} <= set(generic)
    assert all(re.fullmatch("[a-z0-9]+", word) for word in forms + generic)


def test_companies_are_the_active_ones_of_business_forms_with_their_keys(stg_run):
    month = "getvariable('snapshot_month')"
    warehouse = build_int(
        stg_run,
        "INSERT INTO stg.jar_entities VALUES "
        f"({month}, 304000004, 'Individuali įmonė', 'Vilnius, Pylimo g. 47, LT-01141', "
        "DATE '2015-01-10', 810, 0), "
        f"({month}, 304000006, 'Individuali įmonė', 'Vilnius, Totorių g. 5, LT-01120', "
        "DATE '2016-03-01', 810, 0), "
        f"({month}, 304000007, 'UAB \"Ratų centras\"', 'Kaunas, Laisvės al. 1, LT-44001', "
        "DATE '2018-06-01', 310, 0)",
        # this year's row without a trade name leaves the latest one there is
        f"INSERT INTO stg.vmi_taxes VALUES ({month}, 304000004, NULL, 2026, 9, 3000)",
    )
    companies = rows(
        warehouse,
        "SELECT ja_kodas, name, brand_key, core_key, street_key, house_number "
        "FROM int.companies ORDER BY ja_kodas",
    )
    assert companies == [
        (304000001, 'UAB "Kavos namai"', "kavos namai", "namai", "traku", "8"),
        (304000004, "Saulės kepykla", "saules kepykla", "saules", "pylimo", "47"),  # an IĮ
        (304000006, None, None, None, "totoriu", "5"),  # an IĮ without a trade name
        (304000007, 'UAB "Ratų centras"', "ratu centras", "centras", None, None),  # in Kaunas
    ]  # left out: a professional partnership, and an IĮ in liquidation


def test_places_are_scoped_by_the_city_s_bounds_and_their_google_category(stg_run):
    warehouse = build_int(stg_run)
    scopes = dict(rows(warehouse, "SELECT name, scope FROM int.places"))
    assert (scopes["Cozy"], scopes["Senamiestis"], scopes["Grey"]) == (
        "in_scope",
        "outside_city",  # a café in Telšiai, found by searching Vilnius' Senamiestis
        "other_activity",  # a restaurant, found by searching cafés
    )
    assert Counter(scopes.values()) == {"in_scope": 2, "outside_city": 2, "other_activity": 16}
    keys = "SELECT brand_key, core_key, street_key, house_number FROM int.places WHERE name = ?"
    assert warehouse.con.execute(keys, ["Užupio kavinė"]).fetchall() == [
        ("uzupio kavine", "uzupio", "uzupio", "2")
    ]


@pytest.mark.parametrize(
    "position",
    ["latitude = 54.5", "latitude = 54.9", "longitude = 25.0", "longitude = 25.5"],
    ids=["south", "north", "west", "east"],
)
def test_a_place_beyond_any_edge_of_the_city_is_outside_it(stg_run, position):
    warehouse = build_int(stg_run, f"UPDATE stg.google_listings SET {position} WHERE name = 'Cozy'")
    assert rows(warehouse, "SELECT scope FROM int.places WHERE name = 'Cozy'") == [
        ("outside_city",)
    ]


def test_a_place_found_by_several_queries_is_as_busy_and_closed_as_any_saw_it(stg_run):
    warehouse = build_int(
        stg_run,
        "INSERT INTO stg.google_listings SELECT * REPLACE "
        "('kavinė Senamiestis Vilnius' AS query, 2000 AS review_count, false AS closed) "
        "FROM stg.google_listings WHERE name = 'Cozy'",
    )
    cozy = "SELECT review_count, closed FROM int.places WHERE name = 'Cozy'"
    assert rows(warehouse, cozy) == [(2000, True)]  # the fixture month has Cozy closed


def test_a_place_found_under_two_categories_takes_the_one_that_allows_it(stg_run):
    warehouse = build_int(
        stg_run,
        "UPDATE stg.google_listings SET google_category = 'Automobilių servisas' "
        "WHERE name = 'Cozy'",
        "INSERT INTO stg.google_listings SELECT * REPLACE "
        "('car_repair' AS category, 'autoservisas Senamiestis Vilnius' AS query) "
        "FROM stg.google_listings WHERE name = 'Cozy'",
    )
    cozy = "SELECT category, scope FROM int.places WHERE name = 'Cozy'"
    assert rows(warehouse, cozy) == [("car_repair", "in_scope")]


# Candidate companies for each place in scope

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


def candidates(warehouse: Warehouse) -> dict[str, tuple]:
    """Return the evidence of each candidate pair, by the company's name."""
    pairs = rows(
        warehouse,
        "SELECT companies.name, same_brand, same_core, same_building, same_street, "
        "shared_words, fitting_activity "
        "FROM int.candidates JOIN int.companies USING (snapshot_month, ja_kodas)",
    )
    return {name: tuple(evidence) for name, *evidence in pairs}


COZY_BUILDING = "Vilnius, Dominikonų g. 10-3, LT-01120"
COZY_STREET = "Vilnius, Dominikonų g. 3, LT-01120"


def test_a_company_of_the_brand_in_the_place_s_building_shares_all_evidence(stg_run):
    warehouse = build_int(stg_run, company(304100001, 'UAB "Cozy"', COZY_BUILDING, "561100"))
    assert candidates(warehouse) == {'UAB "Cozy"': (True, True, True, True, ["cozy"], True)}


def test_a_company_of_the_brand_elsewhere_shares_the_brand_and_its_activity(stg_run):
    address = "Kaunas, Laisvės al. 5, LT-44001"
    warehouse = build_int(stg_run, company(304100001, 'UAB "Cozy"', address, "107100"))
    assert candidates(warehouse) == {'UAB "Cozy"': (True, True, False, False, ["cozy"], True)}


def test_the_brand_alone_makes_a_candidate(stg_run):
    warehouse = build_int(
        stg_run,
        "UPDATE stg.google_listings SET name = 'Go' WHERE name = 'Cozy'",
        company(304100001, 'UAB "Go"', "Kaunas, Laisvės al. 5, LT-44001"),
    )
    assert candidates(warehouse) == {'UAB "Go"': (True, True, False, False, [], False)}


def test_another_company_in_the_building_shares_only_the_building(stg_run):
    warehouse = build_int(stg_run, company(304100001, 'MB "Rytas"', COZY_BUILDING, "862300"))
    assert candidates(warehouse) == {
        'MB "Rytas"': (False, False, True, True, [], False)  # a dentist's activity
    }


def test_the_latest_activity_code_decides(stg_run):
    warehouse = build_int(
        stg_run, company(304100001, 'UAB "Cozy"', COZY_BUILDING, "561100", "862300")
    )
    assert candidates(warehouse)['UAB "Cozy"'][-1] is False  # a café until July, a dentist now


@pytest.mark.parametrize(("others", "kept"), [(29, True), (30, False)])
def test_a_shared_word_on_the_street_counts_while_30_company_names_at_most_use_it(
    stg_run, others, kept
):
    warehouse = build_int(
        stg_run,
        "UPDATE stg.google_listings SET name = 'Kavinė Cozy Garden' WHERE name = 'Cozy'",
        company(304100001, 'UAB "Garden Fox"', COZY_STREET),
        f"INSERT INTO stg.jar_entities SELECT {MONTH}, 304200000 + i, 'UAB \"Garden ' || i || "
        f"'\"', 'Kaunas, Laisvės al. 1, LT-44001', DATE '2018-01-01', 310, 0 "
        f"FROM range({others}) AS numbers(i)",
    )
    garden_fox = (False, False, False, True, ["garden"], False)
    assert candidates(warehouse) == ({'UAB "Garden Fox"': garden_fox} if kept else {})


def test_a_shared_word_of_three_letters_counts(stg_run):
    warehouse = build_int(
        stg_run,
        "UPDATE stg.google_listings SET name = 'Kavinė Cozy Fox' WHERE name = 'Cozy'",
        company(304100001, 'UAB "Fox Den"', COZY_STREET),
    )
    assert candidates(warehouse) == {'UAB "Fox Den"': (False, False, False, True, ["fox"], False)}


def test_a_place_without_a_street_still_shares_its_words(stg_run):
    warehouse = build_int(
        stg_run,
        "UPDATE stg.google_listings SET address = 'Vilnius' WHERE name = 'Cozy'",
        company(304100001, 'UAB "Cozy"', "Kaunas, Laisvės al. 5, LT-44001"),
    )
    assert candidates(warehouse) == {'UAB "Cozy"': (True, True, False, False, ["cozy"], False)}


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
    warehouse = build_int(
        stg_run,
        f"UPDATE stg.google_listings SET name = '{place}' WHERE name = 'Cozy'",
        company(304100001, name, address),
    )
    assert name not in candidates(warehouse)


def int_checks(warehouse: Warehouse) -> dict[str, tuple[str, int]]:
    results = "SELECT check_name, severity, failing_rows FROM meta.dq_results WHERE layer = 'int'"
    return {name: (severity, failing) for name, severity, failing in rows(warehouse, results)}


def test_int_checks_pass_on_the_fixture_month(stg_run):
    warehouse = build_int(stg_run)
    warehouse.run_checks(stg_run.run, "int")
    assert int_checks(warehouse) == {
        "int_place_addresses": ("warn", 0),
        "int_places_in_scope": ("error", 0),
        "int_unique_keys": ("error", 0),
    }


def test_a_place_in_scope_without_a_house_number_is_reported(stg_run):
    warehouse = build_int(
        stg_run, "UPDATE stg.google_listings SET address = 'Dominikonų g.' WHERE name = 'Cozy'"
    )
    warehouse.run_checks(stg_run.run, "int")
    assert int_checks(warehouse)["int_place_addresses"] == ("warn", 1)


@pytest.mark.parametrize(
    ("breakage", "check"),
    [
        ("INSERT INTO int.companies SELECT * FROM int.companies LIMIT 1", "int_unique_keys"),
        ("INSERT INTO int.places SELECT * FROM int.places LIMIT 1", "int_unique_keys"),
        (
            "INSERT INTO int.candidates SELECT * FROM int.candidates LIMIT 1",
            "int_unique_keys",
        ),
        ("UPDATE int.places SET scope = 'other_activity'", "int_places_in_scope"),
    ],
)
def test_int_checks_stop_the_build(stg_run, breakage, check):
    warehouse = build_int(stg_run, company(304100001, 'UAB "Cozy"', COZY_BUILDING, "561100"))
    warehouse.con.execute(breakage)
    with pytest.raises(DataQualityError, match=check):
        warehouse.run_checks(stg_run.run, "int")
