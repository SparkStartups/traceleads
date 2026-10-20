-- Every stg table has one row per key for the month.
SELECT 'stg.source_files' AS source_table, source || ' ' || file AS duplicate_key
FROM stg.source_files
WHERE snapshot_month = getvariable('snapshot_month')
GROUP BY source, file HAVING count(*) > 1
UNION ALL
SELECT 'stg.jar_entities', ja_kodas::VARCHAR
FROM stg.jar_entities
WHERE snapshot_month = getvariable('snapshot_month')
GROUP BY ja_kodas HAVING count(*) > 1
UNION ALL
SELECT 'stg.sodra_monthly', ja_kodas || ' ' || data_month
FROM stg.sodra_monthly
WHERE snapshot_month = getvariable('snapshot_month')
GROUP BY ja_kodas, data_month HAVING count(*) > 1
UNION ALL
SELECT 'stg.vmi_taxes', ja_kodas || ' ' || tax_year
FROM stg.vmi_taxes
WHERE snapshot_month = getvariable('snapshot_month')
GROUP BY ja_kodas, tax_year HAVING count(*) > 1
UNION ALL
SELECT 'stg.google_listings', query || ' ' || cid
FROM stg.google_listings
WHERE snapshot_month = getvariable('snapshot_month')
GROUP BY query, cid HAVING count(*) > 1
