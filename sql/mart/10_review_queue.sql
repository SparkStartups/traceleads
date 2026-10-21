-- Places whose link needs a person, one row per candidate of the deciding rule: a review rule
-- decided, or the rule found several companies. Such places are not scored. An IĮ's registered
-- address is withheld: it is often its owner's home. A crowded building makes a candidate in it
-- weaker evidence, so each comes with the number of companies registered at its address.
CREATE OR REPLACE VIEW mart.review_queue AS
WITH buildings AS (
    SELECT snapshot_month, street_key, house_number, count(*) AS companies
    FROM int.companies
    GROUP BY snapshot_month, street_key, house_number
)
SELECT
    links.snapshot_month,
    links.cid,
    places.category,
    places.name AS place,
    places.address AS place_address,
    places.review_count,
    links.rule,
    rules.meaning,
    links.candidates,
    candidates.ja_kodas,
    companies.name AS company,
    CASE WHEN NOT forms.named_after_owner THEN companies.address END AS company_address,
    companies.activity_code,
    buildings.companies AS building_companies,  -- none for an address outside the city
    candidates.shared_words
FROM int.links AS links
JOIN int.places AS places USING (snapshot_month, cid)
JOIN int.rules AS rules USING (rule)
JOIN int.candidates AS candidates USING (snapshot_month, cid, rule)
JOIN int.companies AS companies
    ON companies.snapshot_month = links.snapshot_month AND companies.ja_kodas = candidates.ja_kodas
JOIN ref.legal_forms AS forms ON forms.code = companies.legal_form
LEFT JOIN buildings
    ON buildings.snapshot_month = companies.snapshot_month
    AND buildings.street_key = companies.street_key
    AND buildings.house_number = companies.house_number
WHERE links.tier = 'review';
