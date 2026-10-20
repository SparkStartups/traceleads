-- Register of Legal Entities: one row per registered entity.
CREATE TABLE IF NOT EXISTS stg.jar_entities (
    snapshot_month DATE     NOT NULL,
    ja_kodas       INTEGER  NOT NULL,
    legal_name     VARCHAR  NOT NULL,  -- IĮ names are replaced by "Individuali įmonė"
    address        VARCHAR  NOT NULL,  -- registered address, e.g. "Vilnius, Trakų g. 8-5, LT-01132"
    reg_date       DATE     NOT NULL,
    legal_form     SMALLINT NOT NULL,  -- 310 UAB, 960 MB, 810 IĮ, ...
    status         SMALLINT NOT NULL  -- 0: no special legal status; others are liquidation, bankruptcy, ...
);

DELETE FROM stg.jar_entities WHERE snapshot_month = getvariable('snapshot_month');

INSERT INTO stg.jar_entities
SELECT
    getvariable('snapshot_month'),
    ja_kodas::INTEGER,
    ja_pavadinimas::VARCHAR,
    adresas::VARCHAR,
    ja_reg_data::DATE,
    form_kodas::SMALLINT,
    stat_kodas::SMALLINT
FROM 'jar.parquet';
