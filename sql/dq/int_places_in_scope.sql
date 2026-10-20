-- The month has places in scope. None means no Google category matched the configured ones, as
-- when the pages come back in another language, and the lead list would be empty.
SELECT count(*) AS places_in_scope
FROM int.places
WHERE snapshot_month = getvariable('snapshot_month') AND scope = 'in_scope'
HAVING count(*) = 0
