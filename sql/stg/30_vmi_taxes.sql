-- VMI taxes paid: one row per company and year; the current year runs to date. A monthly refresh
-- can leave the previous month's row behind, so only the latest month of each year is kept.
-- Payers without a Lithuanian company code are left out.
CREATE TABLE IF NOT EXISTS stg.vmi_taxes (
    snapshot_month DATE           NOT NULL,
    ja_kodas       INTEGER        NOT NULL,
    trade_name     VARCHAR,                 -- the quoted part of the name, owners' names masked
    tax_year       SMALLINT       NOT NULL,
    months         TINYINT        NOT NULL,  -- 12 for a closed year, else how far the year runs
    amount         DECIMAL(14, 2) NOT NULL
);

DELETE FROM stg.vmi_taxes WHERE snapshot_month = getvariable('snapshot_month');

INSERT INTO stg.vmi_taxes
SELECT
    getvariable('snapshot_month'),
    ja_kodas::INTEGER,
    trade_name::VARCHAR,
    metai::SMALLINT,
    menuo::TINYINT,
    suma::DECIMAL(14, 2)
FROM 'vmi_taxes.parquet'
WHERE ja_kodas IS NOT NULL
QUALIFY row_number() OVER (PARTITION BY ja_kodas, metai ORDER BY menuo DESC) = 1;
