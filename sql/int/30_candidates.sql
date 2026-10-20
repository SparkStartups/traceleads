-- Companies that could run each place in scope, with the evidence the pair shares and the first
-- rule of int.rules it meets. A pair is kept when it shares the brand, the building, or a rare word
-- on the same street: the evidence the rules read. A pair kept may meet no rule, as another
-- company in the building with an activity of its own.
CREATE TABLE IF NOT EXISTS int.candidates (
    snapshot_month   DATE      NOT NULL,
    cid              UBIGINT   NOT NULL,
    ja_kodas         INTEGER   NOT NULL,
    same_brand       BOOLEAN   NOT NULL,
    same_core        BOOLEAN   NOT NULL,
    same_building    BOOLEAN   NOT NULL,
    same_street      BOOLEAN   NOT NULL,
    shared_words     VARCHAR[] NOT NULL,  -- rare words in both names, the street's own name aside
    fitting_activity BOOLEAN   NOT NULL,  -- the company's activity class is one of the category's
    rule             VARCHAR              -- the first rule met; none when the pair meets none
);

DELETE FROM int.candidates WHERE snapshot_month = getvariable('snapshot_month');

INSERT INTO int.candidates
WITH places AS (
    SELECT *
    FROM int.places
    WHERE snapshot_month = getvariable('snapshot_month') AND scope = 'in_scope'
),
companies AS (
    SELECT *
    FROM int.companies
    WHERE snapshot_month = getvariable('snapshot_month')
),
rare_words AS (  -- sharing one says more than sharing 'centras'
    SELECT word
    FROM (SELECT DISTINCT ja_kodas, unnest(string_split(core_key, ' ')) AS word FROM companies)
    CROSS JOIN ref.matching
    WHERE length(word) >= matching.rare_word_min_letters AND NOT regexp_matches(word, '^[0-9]')
    GROUP BY word, matching.rare_word_max_names
    HAVING count(*) <= matching.rare_word_max_names
),
pairs AS (  -- every piece of evidence needs the same brand or the same street
    SELECT places.cid, companies.ja_kodas
    FROM places
    JOIN companies ON companies.brand_key = places.brand_key
    UNION
    SELECT places.cid, companies.ja_kodas
    FROM places
    JOIN companies  -- the same last word, which the same street always has, makes a hash join
        ON string_split(companies.street_key, ' ')[-1] = string_split(places.street_key, ' ')[-1]
        AND int.same_street(companies.street_key, places.street_key)
),
evidence AS (
    SELECT
        pairs.cid,
        pairs.ja_kodas,
        coalesce(companies.brand_key = places.brand_key, false) AS same_brand,
        coalesce(companies.core_key = places.core_key, false) AS same_core,
        coalesce(
            int.same_street(companies.street_key, places.street_key)
                AND companies.house_number = places.house_number,
            false
        ) AS same_building,
        coalesce(int.same_street(companies.street_key, places.street_key), false) AS same_street,
        list_filter(
            list_intersect(
                string_split(places.core_key, ' '), string_split(companies.core_key, ' ')
            ),
            lambda word: NOT list_contains(string_split(coalesce(places.street_key, ''), ' '), word)
        ) AS common_words,
        EXISTS (
            SELECT 1
            FROM ref.activity_classes AS fitting
            WHERE fitting.category = places.category
                AND replace(fitting.activity_class, '.', '') = left(companies.activity_code, 4)
        ) AS fitting_activity
    FROM pairs
    JOIN places USING (cid)
    JOIN companies USING (ja_kodas)
),
shared AS (
    SELECT cid, ja_kodas, list(word ORDER BY word) AS shared_words
    FROM (SELECT cid, ja_kodas, unnest(common_words) AS word FROM evidence)
    SEMI JOIN rare_words USING (word)
    GROUP BY cid, ja_kodas
),
kept AS (
    SELECT evidence.* EXCLUDE (common_words), coalesce(shared.shared_words, []) AS shared_words
    FROM evidence
    LEFT JOIN shared USING (cid, ja_kodas)
    -- a pair that does not share the brand came from the street, so its rare words are on it
    WHERE evidence.same_brand OR evidence.same_building OR shared.shared_words IS NOT NULL
)
SELECT
    getvariable('snapshot_month'),
    cid,
    ja_kodas,
    same_brand,
    same_core,
    same_building,
    same_street,
    shared_words,
    fitting_activity,
    CASE  -- in the order of int.rules
        WHEN same_brand AND same_building THEN 'brand_and_building'
        WHEN same_brand AND fitting_activity THEN 'brand_and_activity'
        WHEN same_core AND same_building THEN 'core_and_building'
        WHEN len(shared_words) > 0 AND same_street THEN 'rare_word_on_street'
        WHEN fitting_activity AND same_building
            AND count(*) FILTER (WHERE fitting_activity AND same_building)
                OVER (PARTITION BY cid) = 1
            THEN 'only_fitting_in_building'
    END
FROM kept;
