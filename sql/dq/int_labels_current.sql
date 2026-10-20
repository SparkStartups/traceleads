-- severity: warn
-- Labels whose link the rules no longer make: they describe an earlier version of the rules or
-- the data, and count in no rule's precision.
SELECT labels.cid, labels.ja_kodas, labels.selection
FROM stg.match_labels AS labels
LEFT JOIN int.links AS links
    ON links.snapshot_month = labels.snapshot_month
    AND links.cid = labels.cid
    AND links.ja_kodas = labels.ja_kodas
WHERE labels.snapshot_month = getvariable('snapshot_month') AND links.cid IS NULL
