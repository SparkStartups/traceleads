-- Sodra's latest month is at most three months before the snapshot month.
SELECT max(data_month) AS latest_month
FROM stg.sodra_monthly
WHERE snapshot_month = getvariable('snapshot_month')
HAVING max(data_month) < getvariable('snapshot_month') - INTERVAL 3 MONTH
