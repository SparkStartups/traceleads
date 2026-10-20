-- Places each rule decided and, of its links a person labelled at random, the share that was
-- right, with a 95% Wilson interval: ten labels pin a rule's precision down to about ±20 points.
-- Links labelled because their company is flagged would bias it, so they stay out.
CREATE OR REPLACE VIEW mart.match_precision AS
WITH decided AS (
    SELECT links.snapshot_month, links.rule, links.ja_kodas, labels.correct
    FROM int.links AS links
    LEFT JOIN stg.match_labels AS labels
        ON labels.snapshot_month = links.snapshot_month
        AND labels.cid = links.cid
        AND labels.ja_kodas = links.ja_kodas
        AND labels.selection = 'random'
),
counts AS (
    SELECT
        snapshot_month,
        rule,
        count(*) AS places,
        count(ja_kodas) AS linked,  -- the rest had several candidates
        count(correct) AS labelled,
        count(*) FILTER (correct) AS correct
    FROM decided
    GROUP BY snapshot_month, rule
),
shares AS (  -- the Wilson interval's terms: share p of n labels, z for 95%
    SELECT *, correct / nullif(labelled, 0) AS p, labelled AS n, 1.96 AS z
    FROM counts
)
SELECT
    shares.snapshot_month,
    rules.rank,
    rules.rule,
    rules.tier,
    shares.places,
    shares.linked,
    shares.labelled,
    shares.correct,
    round(p, 2) AS precision,
    round(
        (p + z ^ 2 / (2 * n) - z * sqrt(p * (1 - p) / n + z ^ 2 / (4 * n ^ 2))) / (1 + z ^ 2 / n), 2
    ) AS precision_low,
    round(
        (p + z ^ 2 / (2 * n) + z * sqrt(p * (1 - p) / n + z ^ 2 / (4 * n ^ 2))) / (1 + z ^ 2 / n), 2
    ) AS precision_high
FROM shares
JOIN int.rules AS rules USING (rule);
