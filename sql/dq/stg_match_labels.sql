-- Every label is readable: its selection is random or flagged, and it says yes or no.
SELECT cid, ja_kodas, selection, correct
FROM stg.match_labels
WHERE snapshot_month = getvariable('snapshot_month')
    AND (selection IS NULL OR correct IS NULL)
