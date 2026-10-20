-- How the list moves with the limits an analyst might dispute: the judged companies tiered again
-- under each gap ratio and minimum of reviews in ref.sensitivity, with how many of the month's
-- leads stay leads. Peers and holds do not depend on these limits, so they stay as scored.
CREATE OR REPLACE VIEW mart.sensitivity AS
WITH tiered AS (
    SELECT
        scores.snapshot_month,
        grid.gap_ratio,
        grid.min_reviews,
        scores.tier = 'lead' AS lead_now,
        mart.tier(
            mart.busy(facts.reviews, scores.category_median_reviews, grid.min_reviews),
            mart.gap(scores.staff_ratio, grid.gap_ratio),
            mart.gap(scores.tax_ratio, grid.gap_ratio),
            scores.staff <= scores.peer_median_staff,
            facts.tax <= scores.peer_median_tax
        ) AS tier
    FROM mart.scores AS scores
    JOIN mart.company_facts AS facts USING (snapshot_month, ja_kodas)
    CROSS JOIN ref.sensitivity AS grid
    WHERE scores.tier <> 'held'
)
SELECT
    snapshot_month,
    gap_ratio,
    min_reviews,
    count(*) FILTER (tier = 'lead') AS leads,
    count(*) FILTER (tier = 'watch') AS watch,
    count(*) FILTER (tier = 'lead' AND lead_now) AS leads_kept
FROM tiered
GROUP BY snapshot_month, gap_ratio, min_reviews;
