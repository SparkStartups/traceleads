-- Google Maps: one row per place a query's results list showed. A place can appear under several
-- queries; the int layer merges them.
CREATE TABLE IF NOT EXISTS stg.google_listings (
    snapshot_month  DATE    NOT NULL,
    query           VARCHAR NOT NULL,  -- e.g. "kavinė Žirmūnai Vilnius"
    cid             UBIGINT NOT NULL,  -- Google's id of the place
    name            VARCHAR NOT NULL,
    category        VARCHAR NOT NULL,  -- ours: the category whose keyword found the place
    google_category VARCHAR,           -- Google's label, e.g. "Odontologijos klinika"
    address         VARCHAR,
    latitude        DOUBLE  NOT NULL,
    longitude       DOUBLE  NOT NULL,
    review_count    INTEGER NOT NULL,
    closed          BOOLEAN NOT NULL,  -- permanently or temporarily closed
    file            VARCHAR NOT NULL  -- the rendered page, as listed in stg.source_files
);

DELETE FROM stg.google_listings WHERE snapshot_month = getvariable('snapshot_month');

INSERT INTO stg.google_listings
SELECT
    getvariable('snapshot_month'),
    query::VARCHAR,
    cid::UBIGINT,
    name::VARCHAR,
    category::VARCHAR,
    google_category::VARCHAR,
    address::VARCHAR,
    latitude::DOUBLE,
    longitude::DOUBLE,
    review_count::INTEGER,
    closed::BOOLEAN,
    file::VARCHAR
FROM 'google_maps.parquet';
