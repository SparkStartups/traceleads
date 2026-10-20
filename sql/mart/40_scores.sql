-- Each company with facts: held, with the reason, when the data cannot judge it; otherwise the
-- peers it is compared with. Peers share its category and legal-form group (owner-operated or
-- not), run one place and are not closed, young or without a tax record, the company left out;
-- they are its review tercile's when that leaves enough of them, else its category's.
CREATE TABLE IF NOT EXISTS mart.scores (
    snapshot_month DATE    NOT NULL,
    ja_kodas       INTEGER NOT NULL,
    hold_reason    VARCHAR,           -- closed, young, no_tax_record or few_peers
    peer_group     VARCHAR,           -- review tercile or category; none when held before peers
    peers          INTEGER
);

DELETE FROM mart.scores WHERE snapshot_month = getvariable('snapshot_month');

INSERT INTO mart.scores
WITH companies AS (
    SELECT
        *,
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
    SELECT *, ntile(3) OVER (PARTITION BY category ORDER BY reviews, ja_kodas) AS tercile
    FROM companies
    WHERE hold_reason IS NULL
),
peer_counts AS (
    SELECT
        company.ja_kodas,
        count(peer.ja_kodas) FILTER (peer.tercile = company.tercile) AS tercile_peers,
        count(peer.ja_kodas) AS category_peers
    FROM assessable AS company
    LEFT JOIN assessable AS peer
        ON peer.category = company.category
        AND peer.owner_operated = company.owner_operated
        AND peer.places = 1
        AND peer.ja_kodas <> company.ja_kodas
    GROUP BY company.ja_kodas
),
grouped AS (  -- the review tercile's peers when there are enough of them, else the category's
    SELECT
        ja_kodas,
        CASE WHEN by_tercile THEN 'review tercile' ELSE 'category' END AS peer_group,
        CASE WHEN by_tercile THEN tercile_peers ELSE category_peers END AS peers
    FROM (
        SELECT *, tercile_peers >= scoring.min_tercile_peers AS by_tercile
        FROM peer_counts
        CROSS JOIN ref.scoring
    )
)
SELECT
    getvariable('snapshot_month'),
    companies.ja_kodas,
    coalesce(
        companies.hold_reason,
        CASE WHEN grouped.peers < scoring.min_peers THEN 'few_peers' END
    ),
    grouped.peer_group,
    grouped.peers
FROM companies
LEFT JOIN grouped USING (ja_kodas)
CROSS JOIN ref.scoring;
