-- Hand labels from data/labels/match_labels.csv: whether a company really runs a place. A link is
-- labelled because it was drawn at random, to measure its rule's precision, or because its company
-- is flagged, to check it. Rows not labelled yet are left out. A selection other than random or
-- flagged, or a label other than yes or no, is kept as none, and its check stops the build.
CREATE TABLE IF NOT EXISTS stg.match_labels (
    snapshot_month DATE    NOT NULL,
    cid            UBIGINT NOT NULL,
    ja_kodas       INTEGER NOT NULL,
    selection      VARCHAR,           -- random or flagged
    correct        BOOLEAN            -- yes or no
);

DELETE FROM stg.match_labels WHERE snapshot_month = getvariable('snapshot_month');

INSERT INTO stg.match_labels
SELECT
    getvariable('snapshot_month'),
    cid::UBIGINT,
    ja_kodas::INTEGER,
    CASE WHEN trim(selection) IN ('random', 'flagged') THEN trim(selection) END,
    CASE trim(correct) WHEN 'yes' THEN true WHEN 'no' THEN false END
FROM read_csv('match_labels.csv', header = true, all_varchar = true)
WHERE coalesce(trim(correct), '') <> '';
