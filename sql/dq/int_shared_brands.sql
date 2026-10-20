-- severity: warn
-- Automatic links by brand and activity whose brand another company also uses: the brand alone may
-- not tell which of them runs the place.
SELECT links.cid, links.ja_kodas, companies.brand_key, count(*) AS other_companies
FROM int.links AS links
JOIN int.companies AS companies USING (snapshot_month, ja_kodas)
JOIN int.companies AS others
    ON others.snapshot_month = companies.snapshot_month
    AND others.brand_key = companies.brand_key
    AND others.ja_kodas <> companies.ja_kodas
WHERE links.snapshot_month = getvariable('snapshot_month')
    AND links.rule = 'brand_and_activity'
GROUP BY links.cid, links.ja_kodas, companies.brand_key
