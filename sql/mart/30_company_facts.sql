-- Companies with an automatic link: how busy their places are on Google and what they declare.
-- Sodra lists every employer, so a month without a row had nobody insured. VMI leaves some real
-- payers out, so a missing tax row stays unknown.
-- Whether Sodra's ``data_month`` is one of the latest ``months`` that staff averages.
CREATE OR REPLACE MACRO mart.staff_month(data_month, latest, months) AS
    data_month > latest - to_months(months);

CREATE TABLE IF NOT EXISTS mart.company_facts (
    snapshot_month DATE           NOT NULL,
    ja_kodas       INTEGER        NOT NULL,
    category       VARCHAR        NOT NULL,  -- of its busiest place
    places         INTEGER        NOT NULL,  -- places in scope linked to it automatically
    reviews        INTEGER        NOT NULL,  -- Google reviews of those places
    closed         BOOLEAN        NOT NULL,  -- every place is closed, for good or for now
    owner_operated BOOLEAN        NOT NULL,  -- an MB or IĮ: the owners need not be on the payroll
    reg_date       DATE           NOT NULL,
    insured        DOUBLE         NOT NULL,  -- average insured over Sodra's latest months
    tax_year       SMALLINT       NOT NULL,  -- the latest full year VMI has published
    tax            DECIMAL(14, 2)            -- taxes paid that year; none without a 12-month row
);

DELETE FROM mart.company_facts WHERE snapshot_month = getvariable('snapshot_month');

INSERT INTO mart.company_facts
WITH linked AS (
    SELECT
        links.ja_kodas,
        first(places.category ORDER BY places.review_count DESC, places.category) AS category,
        count(*) AS places,
        sum(places.review_count) AS reviews,
        bool_and(places.closed) AS closed
    FROM int.links AS links
    JOIN int.places AS places USING (snapshot_month, cid)
    WHERE links.snapshot_month = getvariable('snapshot_month') AND links.tier = 'automatic'
    GROUP BY links.ja_kodas
),
sodra AS (
    SELECT ja_kodas, data_month, insured
    FROM stg.sodra_monthly
    WHERE snapshot_month = getvariable('snapshot_month')
),
latest AS (
    SELECT max(data_month) AS staff_month FROM sodra
),
full_year AS (  -- in early January, VMI has not published December yet
    SELECT max(tax_year) AS tax_year
    FROM stg.vmi_taxes
    WHERE snapshot_month = getvariable('snapshot_month') AND months = 12
),
staff AS (
    SELECT
        linked.ja_kodas,
        coalesce(
            sum(sodra.insured)
                FILTER (mart.staff_month(sodra.data_month, staff_month, scoring.staff_months)),
            0
        ) / scoring.staff_months AS insured
    FROM linked
    CROSS JOIN latest
    CROSS JOIN ref.scoring
    LEFT JOIN sodra USING (ja_kodas)
    GROUP BY linked.ja_kodas, scoring.staff_months
)
SELECT
    getvariable('snapshot_month'),
    linked.ja_kodas,
    linked.category,
    linked.places,
    linked.reviews,
    linked.closed,
    forms.owner_operated,
    companies.reg_date,
    staff.insured,
    full_year.tax_year,
    taxes.amount
FROM linked
CROSS JOIN full_year
JOIN staff USING (ja_kodas)
JOIN int.companies AS companies
    ON companies.snapshot_month = getvariable('snapshot_month')
    AND companies.ja_kodas = linked.ja_kodas
JOIN ref.legal_forms AS forms ON forms.code = companies.legal_form
LEFT JOIN stg.vmi_taxes AS taxes
    ON taxes.snapshot_month = getvariable('snapshot_month')
    AND taxes.ja_kodas = linked.ja_kodas
    AND taxes.tax_year = full_year.tax_year
    AND taxes.months = 12;
