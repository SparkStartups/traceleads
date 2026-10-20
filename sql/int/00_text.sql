-- Keys that let a Google place and a registered company be compared: a name's brand and core, an
-- address's street and house number. A key is NULL when nothing is left of the text, and NULL
-- never equals anything, so an empty key never links.

-- Lower case, no accents, words of letters and digits separated by single spaces.
CREATE OR REPLACE MACRO int.plain_text(text) AS
    nullif(trim(regexp_replace(strip_accents(lower(text)), '[^a-z0-9]+', ' ', 'g')), '');

-- The words of plain text that are not in the list `words`.
CREATE OR REPLACE MACRO int.without_words(text, words) AS nullif(array_to_string(
    list_filter(string_split(text, ' '), lambda word: NOT list_contains(words, word)), ' '
), '');

-- The last quoted part of a name, even when quotes are nested: 'MB "Kepykla "Sodas"' gives 'Sodas'.
-- The collector cuts VMI payers' trade names with the same pattern.
CREATE OR REPLACE MACRO int.quoted_part(name) AS
    nullif(regexp_extract(name, '[„"“]([^„"“”]+)[“"”][^„"“”]*$', 1), '');

-- A name's brand: the quoted part of a legal name ('UAB "Kavos namai"'), else the whole name, as
-- plain text without the words of legal forms (`form_words`: 'uab', 'uzdaroji', ...). A Google
-- place's name goes through the same steps.
CREATE OR REPLACE MACRO int.brand_key(name, form_words) AS
    int.without_words(int.plain_text(coalesce(int.quoted_part(name), name)), form_words);

-- A brand without the words that say what a business is or where (`generic_words`: 'kavine',
-- 'vilniaus', ...): 'kavine cozy' gives 'cozy'.
CREATE OR REPLACE MACRO int.core_key(brand, generic_words) AS
    int.without_words(brand, generic_words);

-- The parts of an address between commas or bars, as plain text.
CREATE OR REPLACE MACRO int.address_parts(address) AS
    list_transform(regexp_split_to_array(address, '[,|]'), lambda part: int.plain_text(part));

-- A plain-text address part split at its street type ('g', 'pr', 'a', ...) into the street name
-- before it and the rest after it; empty strings without a type. The name needs a word of two
-- letters, so the initial of 'a mickeviciaus g 64' is not taken for the 'a' of a square.
CREATE OR REPLACE MACRO int.street_split(part) AS regexp_extract(
    part,
    '^(.*?[a-z]{2}.*?) (?:g|gatve|pr|prospektas|al|aleja|a|aikste|pl|plentas|skg|skersgatvis|'
    'kel|kl|kelias|tak|takas|krantine)(?: (.*))?$',
    ['name', 'rest']
);

-- The first word of plain text that is a house number, digits and at most one letter: '31a'.
CREATE OR REPLACE MACRO int.first_house_number(text) AS list_filter(
    string_split(text, ' '), lambda word: regexp_matches(word, '^[0-9]{1,4}[a-z]?$')
)[1];

-- The part of an address that holds the street: the first with a street type ('PC CUP, Upės g. 9'
-- gives 'upes g 9'), else the first with a house number ('Kalvarijų 125-5korpusas').
CREATE OR REPLACE MACRO int.street_part(address) AS coalesce(
    list_filter(int.address_parts(address), lambda part: int.street_split(part).name <> '')[1],
    list_filter(
        int.address_parts(address), lambda part: int.first_house_number(part) IS NOT NULL
    )[1]
);

-- The street of an address without its type, initials or numbers: 'S. Žukausko g. 39',
-- '39 Žukausko gatvė' and 'Vilnius, S. Žukausko g. 39-2, LT-09129' all give 'zukausko'.
CREATE OR REPLACE MACRO int.street_key(address) AS nullif(array_to_string(list_filter(
    string_split(
        coalesce(
            nullif(int.street_split(int.street_part(address)).name, ''), int.street_part(address)
        ),
        ' '
    ),
    lambda word: length(word) > 1 AND NOT regexp_matches(word, '^[0-9]')
), ' '), '');

-- The building number of an address, without the flat: the first after the street type
-- ('Sausio 13-osios g. 11-38' gives '11'), else the first in the street part ('77 Vėtrungių g.').
CREATE OR REPLACE MACRO int.house_number(address) AS coalesce(
    int.first_house_number(int.street_split(int.street_part(address)).rest),
    int.first_house_number(int.street_part(address))
);

-- Whether two street keys name the same street. The register often spells out a first name that
-- Google gives as an initial, which keys drop: 'loretos asanaviciutes' and 'asanaviciutes'.
CREATE OR REPLACE MACRO int.same_street(a, b) AS
    a = b OR ends_with(a, ' ' || b) OR ends_with(b, ' ' || a);
