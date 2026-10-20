-- Sodra: insured people per employer and month. A company with no insured people has no row.
-- Insurers without a Lithuanian company code (foreign entities) are left out.
CREATE TABLE IF NOT EXISTS stg.sodra_monthly (
    snapshot_month DATE    NOT NULL,
    ja_kodas       INTEGER NOT NULL,
    data_month     DATE    NOT NULL,
    insured        INTEGER NOT NULL,
    evrk           VARCHAR  -- EVRK 2.1 activity code, six digits
);

DELETE FROM stg.sodra_monthly WHERE snapshot_month = getvariable('snapshot_month');

INSERT INTO stg.sodra_monthly
SELECT
    getvariable('snapshot_month'),
    "jarCode"::INTEGER,
    strptime("month", '%Y%m')::DATE,
    "numInsured"::INTEGER,
    lpad("ecoActCode", 6, '0')  -- the file drops leading zeros: 15000 is 01.50.00
FROM 'sodra.parquet'
WHERE "jarCode" IS NOT NULL;
