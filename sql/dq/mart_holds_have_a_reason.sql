-- A company is held exactly when it has a hold reason, so the list can say why it is not judged.
SELECT ja_kodas, tier, hold_reason
FROM mart.scores
WHERE snapshot_month = getvariable('snapshot_month')
    AND (tier = 'held') <> (hold_reason IS NOT NULL)
