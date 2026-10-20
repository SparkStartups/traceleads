-- Each month's scored companies against the month built before it: new, gone, re-tiered or
-- unchanged, with what moved them. Every build scores all months with the same code, so a change
-- comes from the data. The first month has nothing to compare with.
CREATE OR REPLACE VIEW mart.month_over_month AS
WITH months AS (
    SELECT snapshot_month, lag(snapshot_month) OVER (ORDER BY snapshot_month) AS previous_month
    FROM (SELECT DISTINCT snapshot_month FROM mart.scores)
),
scored AS (
    SELECT scores.*, facts.category, facts.reviews, facts.tax
    FROM mart.scores AS scores
    JOIN mart.company_facts AS facts USING (snapshot_month, ja_kodas)
),
previous AS (  -- dated with the month it is compared with
    SELECT months.snapshot_month, scored.* EXCLUDE (snapshot_month)
    FROM months
    JOIN scored ON scored.snapshot_month = months.previous_month
)
SELECT
    snapshot_month,
    months.previous_month,
    ja_kodas,
    coalesce(now.category, before.category) AS category,
    before.tier AS previous_tier,
    now.tier,
    CASE
        WHEN before.tier IS NULL THEN 'new'
        WHEN now.tier IS NULL THEN 'gone'
        WHEN now.tier <> before.tier THEN 'tier changed'
        ELSE 'unchanged'
    END AS change,
    list_filter(  -- a cause comparing a figure one month lacks is NULL, so it is left out
        [
            CASE WHEN before.tier IS NULL THEN 'linked to a place this month' END,
            CASE WHEN now.tier IS NULL THEN 'no longer linked to a place' END,
            CASE WHEN now.hold_reason IS DISTINCT FROM before.hold_reason
                AND now.tier IS NOT NULL AND before.tier IS NOT NULL
                THEN coalesce('held: ' || now.hold_reason, 'judged again') END,
            CASE WHEN now.category <> before.category
                THEN 'category ' || before.category || ' → ' || now.category END,
            CASE WHEN now.busy <> before.busy
                THEN CASE WHEN now.busy THEN 'busy' ELSE 'no longer busy' END
                    || ': ' || before.reviews || ' → ' || now.reviews
                    || ' reviews, category median ' || before.category_median_reviews || ' → '
                    || now.category_median_reviews END,
            -- on a new tier, the figures that may have crossed a gap or a peers' median
            CASE WHEN now.tier <> before.tier
                AND (now.staff <> before.staff OR now.peer_median_staff <> before.peer_median_staff)
                THEN 'staff ' || round(before.staff, 1) || ' → ' || round(now.staff, 1)
                    || ', peers ' || round(before.peer_median_staff, 1) || ' → '
                    || round(now.peer_median_staff, 1) END,
            CASE WHEN now.tier <> before.tier
                AND (now.tax <> before.tax OR now.peer_median_tax <> before.peer_median_tax)
                THEN 'tax ' || before.tax::BIGINT || ' → ' || now.tax::BIGINT || ', peers '
                    || before.peer_median_tax::BIGINT || ' → ' || now.peer_median_tax::BIGINT END
        ],
        lambda cause: cause IS NOT NULL
    ) AS causes
FROM scored AS now
FULL JOIN previous AS before USING (snapshot_month, ja_kodas)
JOIN months USING (snapshot_month)
WHERE months.previous_month IS NOT NULL;
