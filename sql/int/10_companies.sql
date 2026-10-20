-- Active companies of the legal forms that run businesses, with the keys a place is compared by.
-- The register hides the name of a company named after its owner (IĮ), so such a company goes by
-- its VMI trade name, or by no name. Building keys are kept only for an address in the city.
CREATE TABLE IF NOT EXISTS int.companies (
    snapshot_month DATE     NOT NULL,
    ja_kodas       INTEGER  NOT NULL,
    name           VARCHAR,            -- none for an IĮ without a trade name
    address        VARCHAR  NOT NULL,  -- registered address
    legal_form     SMALLINT NOT NULL,
    reg_date       DATE     NOT NULL,
    brand_key      VARCHAR,
    core_key       VARCHAR,
    street_key     VARCHAR,            -- none outside the city
    house_number   VARCHAR,
    activity_code  VARCHAR             -- the latest in Sodra; none without insured staff
);

DELETE FROM int.companies WHERE snapshot_month = getvariable('snapshot_month');

INSERT INTO int.companies
WITH trade_names AS (
    SELECT ja_kodas, arg_max(trade_name, tax_year) AS trade_name  -- the latest year with one
    FROM stg.vmi_taxes
    WHERE snapshot_month = getvariable('snapshot_month')
    GROUP BY ja_kodas
),
activities AS (
    SELECT ja_kodas, arg_max(evrk, data_month) AS activity_code  -- the latest month with one
    FROM stg.sodra_monthly
    WHERE snapshot_month = getvariable('snapshot_month')
    GROUP BY ja_kodas
),
named AS (
    SELECT
        jar.ja_kodas,
        CASE WHEN forms.named_after_owner THEN trade_names.trade_name ELSE jar.legal_name END
            AS name,
        jar.address,
        jar.legal_form,
        jar.reg_date,
        CASE WHEN jar.address LIKE city.name || ',%' THEN jar.address END AS city_address
    FROM stg.jar_entities AS jar
    JOIN ref.legal_forms AS forms ON forms.code = jar.legal_form
    LEFT JOIN trade_names USING (ja_kodas)
    CROSS JOIN ref.city
    WHERE jar.snapshot_month = getvariable('snapshot_month')
        AND jar.status = 0  -- not in liquidation, bankruptcy or reorganisation
),
branded AS (
    SELECT named.*, int.brand_key(named.name, words.form_words) AS brand_key, words.generic_words
    FROM named
    CROSS JOIN int.key_words AS words
)
SELECT
    getvariable('snapshot_month'),
    ja_kodas,
    name,
    address,
    legal_form,
    reg_date,
    brand_key,
    int.core_key(brand_key, generic_words),
    int.street_key(city_address),
    int.house_number(city_address),
    activities.activity_code
FROM branded
LEFT JOIN activities USING (ja_kodas);
