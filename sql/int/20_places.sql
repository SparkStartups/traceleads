-- Google places once each, with the keys a company is compared by, and their scope: in_scope
-- inside the city's bounds with a Google category of the category that found them, else
-- outside_city or other_activity (a café search also finds restaurants, and places without a
-- Google category).
CREATE TABLE IF NOT EXISTS int.places (
    snapshot_month DATE    NOT NULL,
    cid            UBIGINT NOT NULL,
    name           VARCHAR NOT NULL,
    category       VARCHAR NOT NULL,
    address        VARCHAR,
    review_count   INTEGER NOT NULL,  -- the most any query saw
    closed         BOOLEAN NOT NULL,  -- closed in any query
    brand_key      VARCHAR,
    core_key       VARCHAR,
    street_key     VARCHAR,
    house_number   VARCHAR,
    scope          VARCHAR NOT NULL
);

DELETE FROM int.places WHERE snapshot_month = getvariable('snapshot_month');

INSERT INTO int.places
-- A place per category that found it, split by whether its Google category is allowed there: the
-- queries can disagree on the Google category ('Desertų restoranas' in one, 'Renginių vieta' in
-- another).
WITH found AS (
    SELECT
        listings.cid,
        listings.category,
        allowed.category IS NOT NULL AS allowed,
        arg_min(listings.name, listings.query) AS name,
        arg_min(listings.address, listings.query) AS address,
        arg_min(listings.latitude, listings.query) AS latitude,
        arg_min(listings.longitude, listings.query) AS longitude,
        max(listings.review_count) AS review_count,
        bool_or(listings.closed) AS closed
    FROM stg.google_listings AS listings
    LEFT JOIN ref.google_categories AS allowed
        ON allowed.category = listings.category
        AND allowed.google_category = listings.google_category
    WHERE listings.snapshot_month = getvariable('snapshot_month')
    GROUP BY listings.cid, listings.category, allowed.category
),
places AS (  -- found under several categories, a place takes one that allows its Google category
    SELECT *
    FROM found
    QUALIFY row_number() OVER (PARTITION BY cid ORDER BY allowed DESC, category) = 1
),
branded AS (
    SELECT places.*, int.brand_key(places.name, words.form_words) AS brand_key, words.generic_words
    FROM places
    CROSS JOIN int.key_words AS words
)
SELECT
    getvariable('snapshot_month'),
    branded.cid,
    branded.name,
    branded.category,
    branded.address,
    branded.review_count,
    branded.closed,
    branded.brand_key,
    int.core_key(branded.brand_key, branded.generic_words),
    int.street_key(branded.address),
    int.house_number(branded.address),
    CASE
        WHEN branded.latitude NOT BETWEEN city.lat_min AND city.lat_max
            OR branded.longitude NOT BETWEEN city.lng_min AND city.lng_max
            THEN 'outside_city'
        WHEN NOT branded.allowed THEN 'other_activity'
        ELSE 'in_scope'
    END
FROM branded
CROSS JOIN ref.city;
