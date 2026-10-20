import pytest

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
