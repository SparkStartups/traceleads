-- Raw files behind each month, with URL, SHA-256 and download time
-- Google's result pages are left out; drop the filter to list them.
SELECT snapshot_month, source, file, period, url, sha256, fetched_at
FROM stg.source_files
WHERE source <> 'google_maps'
ORDER BY snapshot_month DESC, source, file;
