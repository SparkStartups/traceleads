-- Company codes have nine digits in every source.
SELECT source_table, ja_kodas
FROM (
    SELECT 'stg.jar_entities' AS source_table, snapshot_month, ja_kodas FROM stg.jar_entities
    UNION ALL
    SELECT 'stg.sodra_monthly', snapshot_month, ja_kodas FROM stg.sodra_monthly
    UNION ALL
    SELECT 'stg.vmi_taxes', snapshot_month, ja_kodas FROM stg.vmi_taxes
)
WHERE snapshot_month = getvariable('snapshot_month')
    AND ja_kodas NOT BETWEEN 100000000 AND 999999999
