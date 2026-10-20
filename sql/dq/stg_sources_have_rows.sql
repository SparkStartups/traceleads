-- Every source table has rows for the month.
SELECT source_table
FROM (
    SELECT 'stg.jar_entities' AS source_table, count(*) AS n
    FROM stg.jar_entities WHERE snapshot_month = getvariable('snapshot_month')
    UNION ALL
    SELECT 'stg.sodra_monthly', count(*)
    FROM stg.sodra_monthly WHERE snapshot_month = getvariable('snapshot_month')
    UNION ALL
    SELECT 'stg.vmi_taxes', count(*)
    FROM stg.vmi_taxes WHERE snapshot_month = getvariable('snapshot_month')
    UNION ALL
    SELECT 'stg.google_listings', count(*)
    FROM stg.google_listings WHERE snapshot_month = getvariable('snapshot_month')
)
WHERE n = 0
