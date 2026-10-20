-- Every int table has one row per key for the month.
SELECT 'int.companies' AS source_table, ja_kodas::VARCHAR AS duplicate_key
FROM int.companies
WHERE snapshot_month = getvariable('snapshot_month')
GROUP BY ja_kodas HAVING count(*) > 1
UNION ALL
SELECT 'int.places', cid::VARCHAR
FROM int.places
WHERE snapshot_month = getvariable('snapshot_month')
GROUP BY cid HAVING count(*) > 1
UNION ALL
SELECT 'int.candidates', cid || ' ' || ja_kodas
FROM int.candidates
WHERE snapshot_month = getvariable('snapshot_month')
GROUP BY cid, ja_kodas HAVING count(*) > 1
UNION ALL
SELECT 'int.links', cid::VARCHAR
FROM int.links
WHERE snapshot_month = getvariable('snapshot_month')
GROUP BY cid HAVING count(*) > 1
