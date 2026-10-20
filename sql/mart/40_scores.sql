-- Each company with facts and its tier. A company the data cannot judge is held, with the reason.
-- The others are compared with peers that share their category and legal-form group (owner-
-- operated or not), run one place and are not closed, young or without a tax record, the company
-- left out: the peers of its review tercile when that leaves enough of them, else its category's.
-- A busy company declaring staff and tax at or below a share of its peers' medians is a lead; one
-- of the two puts it on watch, unless its other figure is above the peers' median. Every company
-- carries the innocent explanations its data makes plausible, to rule out before acting on it.

-- The judgement, shared with the sensitivity grid, which varies min_reviews and gap_ratio.
CREATE OR REPLACE MACRO mart.busy(reviews, category_median_reviews, min_reviews) AS
    reviews >= category_median_reviews AND reviews >= min_reviews;

CREATE OR REPLACE MACRO mart.gap(ratio, gap_ratio) AS coalesce(ratio <= gap_ratio, false);

-- A company declaring more than its peers' median on the other figure is not quiet on paper.
CREATE OR REPLACE MACRO mart.tier(busy, staff_gap, tax_gap, staff_within, tax_within) AS CASE
    WHEN busy AND staff_gap AND tax_gap THEN 'lead'
    WHEN busy AND staff_gap AND tax_within THEN 'watch'
    WHEN busy AND tax_gap AND staff_within THEN 'watch'
    ELSE 'not_flagged'
END;

CREATE TABLE IF NOT EXISTS mart.scores (
    snapshot_month          DATE    NOT NULL,
    ja_kodas                INTEGER NOT NULL,
    tier                    VARCHAR NOT NULL,  -- lead, watch, not_flagged or held
    rank                    INTEGER,           -- leads, then watch, by the euro gap to peers' tax
    hold_reason             VARCHAR,           -- closed, young, no_tax_record or few_peers
    peer_group              VARCHAR,           -- review tercile or category
    peers                   INTEGER,
    category_median_reviews DOUBLE,            -- of the category, closed, young or no-tax left out
    busy                    BOOLEAN,
    staff                   DOUBLE  NOT NULL,  -- insured, plus an owner for an MB or IĮ
    peer_median_staff       DOUBLE,
    staff_ratio             DOUBLE,
    staff_gap               BOOLEAN,
    peer_median_tax         DOUBLE,
    tax_ratio               DOUBLE,
    tax_gap                 BOOLEAN,
    tax_gap_eur             DOUBLE,            -- the peers' median tax minus the company's
    explanations            VARCHAR[] NOT NULL
);

DELETE FROM mart.scores WHERE snapshot_month = getvariable('snapshot_month');

INSERT INTO mart.scores
WITH companies AS (
    SELECT
        *,
        insured_3m + owner_operated::INTEGER AS staff,
        CASE
            WHEN closed THEN 'closed'
            -- registered after January of the tax year, so it paid tax for part of it only
            WHEN reg_date >= make_date(tax_year, 2, 1) THEN 'young'
            WHEN tax IS NULL THEN 'no_tax_record'
        END AS hold_reason
    FROM mart.company_facts
    WHERE snapshot_month = getvariable('snapshot_month')
),
assessable AS (
    SELECT
        *,
        ntile(3) OVER (PARTITION BY category ORDER BY reviews, ja_kodas) AS tercile,
        median(reviews) OVER (PARTITION BY category) AS category_median_reviews
    FROM companies
    WHERE hold_reason IS NULL
),
peer_values AS (  -- each company's peers, with how many of them share its review tercile
    SELECT
        company.ja_kodas,
        peer.tercile = company.tercile AS same_tercile,
        count(*) FILTER (peer.tercile = company.tercile) OVER (PARTITION BY company.ja_kodas)
            AS tercile_peers,
        peer.staff,
        peer.tax
    FROM assessable AS company
    JOIN assessable AS peer
        ON peer.category = company.category
        AND peer.owner_operated = company.owner_operated
        AND peer.places = 1
        AND peer.ja_kodas <> company.ja_kodas
),
peer_medians AS (  -- the review tercile's peers when there are enough of them, else the category's
    SELECT
        ja_kodas,
        any_value(tercile_peers >= scoring.min_tercile_peers) AS by_tercile,
        count(*) AS peer_count,
        median(staff) AS peer_median_staff,
        median(tax) AS peer_median_tax
    FROM peer_values
    CROSS JOIN ref.scoring
    WHERE same_tercile OR tercile_peers < scoring.min_tercile_peers
    GROUP BY ja_kodas
),
scored AS (
    SELECT
        assessable.ja_kodas,
        assessable.category_median_reviews,
        CASE WHEN peer_medians.by_tercile THEN 'review tercile' ELSE 'category' END AS peer_group,
        coalesce(peer_medians.peer_count, 0) AS peers,
        mart.busy(assessable.reviews, assessable.category_median_reviews, scoring.min_reviews)
            AS busy,
        peer_medians.peer_median_staff,
        assessable.staff / nullif(peer_medians.peer_median_staff, 0) AS staff_ratio,
        mart.gap(staff_ratio, scoring.gap_ratio) AS staff_gap,
        peer_medians.peer_median_tax,
        assessable.tax / nullif(peer_medians.peer_median_tax, 0) AS tax_ratio,
        mart.gap(tax_ratio, scoring.gap_ratio) AS tax_gap,
        peer_medians.peer_median_tax - assessable.tax AS tax_gap_eur,
        CASE WHEN peers < scoring.min_peers THEN 'held' ELSE mart.tier(
            busy,
            staff_gap,
            tax_gap,
            assessable.staff <= peer_medians.peer_median_staff,
            assessable.tax <= peer_medians.peer_median_tax
        ) END AS tier
    FROM assessable
    LEFT JOIN peer_medians USING (ja_kodas)
    CROSS JOIN ref.scoring
)
SELECT
    getvariable('snapshot_month'),
    companies.ja_kodas,
    coalesce(scored.tier, 'held'),
    CASE WHEN scored.tier IN ('lead', 'watch') THEN row_number() OVER (
        PARTITION BY scored.tier IN ('lead', 'watch')
        ORDER BY scored.tier = 'watch', scored.tax_gap_eur DESC, companies.ja_kodas
    ) END,
    coalesce(companies.hold_reason, CASE WHEN scored.tier = 'held' THEN 'few_peers' END),
    scored.peer_group,
    scored.peers,
    scored.category_median_reviews,
    scored.busy,
    companies.staff,
    scored.peer_median_staff,
    scored.staff_ratio,
    scored.staff_gap,
    scored.peer_median_tax,
    scored.tax_ratio,
    scored.tax_gap,
    scored.tax_gap_eur,
    list_filter(
        [
            CASE WHEN companies.owner_operated
                THEN 'owner-operated: one owner counted; more may work off the payroll' END,
            CASE WHEN companies.reg_date BETWEEN
                    make_date(companies.tax_year, 1, 1) - to_months(scoring.young_months)
                    AND make_date(companies.tax_year, 12, 31)
                THEN 'registered in ' || strftime(companies.reg_date, '%Y-%m') || ', so '
                    || companies.tax_year || ' was among its first years' END,
            CASE WHEN companies.places > 1
                THEN 'runs ' || companies.places || ' places; peers run one' END,
            category_explanations.explanation,
            CASE WHEN companies.insured_3m = 0 AND companies.tax < scoring.little_tax
                THEN 'nobody insured and almost no tax: it may no longer run the place' END
        ],
        lambda explanation: explanation IS NOT NULL
    )
FROM companies
LEFT JOIN scored USING (ja_kodas)
LEFT JOIN ref.category_explanations USING (category)
CROSS JOIN ref.scoring;
