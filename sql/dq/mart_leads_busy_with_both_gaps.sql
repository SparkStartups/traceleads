-- Every lead is busy and declares both staff and tax at most the gap ratio of its peers' medians.
SELECT ja_kodas, busy, staff_gap, tax_gap
FROM mart.scores
WHERE snapshot_month = getvariable('snapshot_month')
    AND tier = 'lead'
    AND (busy AND staff_gap AND tax_gap) IS NOT TRUE
