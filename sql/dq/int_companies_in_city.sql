-- The month has companies with a street in the city. None means the register's addresses no
-- longer start with the city's name, so only the brand and activity rule links.
SELECT count(*) AS companies_in_city
FROM int.companies
WHERE snapshot_month = getvariable('snapshot_month') AND street_key IS NOT NULL
HAVING count(*) = 0
