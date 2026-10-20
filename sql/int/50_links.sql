-- One row per place in scope: the company it is linked to, or why it is not. The first rule its
-- candidates meet decides: one company under it gives a link of the rule's tier, several send the
-- place to review without a company, and none leaves it unmatched. A link a person labelled wrong
-- is rejected, so it is never scored.
CREATE TABLE IF NOT EXISTS int.links (
    snapshot_month DATE    NOT NULL,
    cid            UBIGINT NOT NULL,
    ja_kodas       INTEGER,           -- none when unmatched, or when the rule found several
    tier           VARCHAR NOT NULL,  -- automatic, review, rejected or unmatched
    rule           VARCHAR,           -- the deciding rule; none when unmatched
    candidates     INTEGER NOT NULL   -- companies the deciding rule found
);

DELETE FROM int.links WHERE snapshot_month = getvariable('snapshot_month');

INSERT INTO int.links
WITH deciding AS (
    SELECT candidates.cid, candidates.ja_kodas, rules.rule, rules.tier
    FROM int.candidates AS candidates
    JOIN int.rules AS rules USING (rule)
    WHERE candidates.snapshot_month = getvariable('snapshot_month')
    QUALIFY rules.rank = min(rules.rank) OVER (PARTITION BY candidates.cid)
),
decisions AS (
    SELECT
        cid,
        any_value(rule) AS rule,
        any_value(tier) AS tier,
        count(*) AS candidates,
        CASE WHEN count(*) = 1 THEN any_value(ja_kodas) END AS ja_kodas
    FROM deciding
    GROUP BY cid
)
SELECT
    getvariable('snapshot_month'),
    places.cid,
    decisions.ja_kodas,
    CASE
        WHEN decisions.cid IS NULL THEN 'unmatched'
        WHEN EXISTS (
            SELECT 1
            FROM stg.match_labels AS labels
            WHERE labels.snapshot_month = places.snapshot_month
                AND labels.cid = places.cid
                AND labels.ja_kodas = decisions.ja_kodas
                AND NOT labels.correct
        ) THEN 'rejected'
        WHEN decisions.candidates = 1 THEN decisions.tier
        ELSE 'review'
    END,
    decisions.rule,
    coalesce(decisions.candidates, 0)
FROM int.places AS places
LEFT JOIN decisions USING (cid)
WHERE places.snapshot_month = getvariable('snapshot_month') AND places.scope = 'in_scope';
