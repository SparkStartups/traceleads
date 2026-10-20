-- Every mart table has one row per key for the month.
SELECT 'mart.company_facts' AS source_table, ja_kodas::VARCHAR AS duplicate_key
FROM mart.company_facts
WHERE snapshot_month = getvariable('snapshot_month')
GROUP BY ja_kodas HAVING count(*) > 1
UNION ALL
SELECT 'mart.scores', ja_kodas::VARCHAR
FROM mart.scores
WHERE snapshot_month = getvariable('snapshot_month')
GROUP BY ja_kodas HAVING count(*) > 1
