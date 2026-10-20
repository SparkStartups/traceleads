-- severity: warn
-- Places in scope whose address gave no street or no house number, so only their name can link
-- them to a company.
SELECT cid, name, address
FROM int.places
WHERE snapshot_month = getvariable('snapshot_month')
    AND scope = 'in_scope'
    AND (street_key IS NULL OR house_number IS NULL)
