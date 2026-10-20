-- severity: warn
-- Queries whose results list was empty, or full: Google Maps shows about 20 places at a time, so
-- a full list may have left places out.
SELECT files.file, count(listings.cid) AS listings
FROM stg.source_files AS files
LEFT JOIN stg.google_listings AS listings
    ON listings.snapshot_month = files.snapshot_month AND listings.file = files.file
WHERE files.snapshot_month = getvariable('snapshot_month') AND files.source = 'google_maps'
GROUP BY files.file
HAVING count(listings.cid) = 0 OR count(listings.cid) >= 20
