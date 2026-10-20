-- Places whose link needs a person, one row per candidate of the deciding rule: a review rule
-- decided, or the rule found several companies. Such places are not scored.
CREATE OR REPLACE VIEW mart.review_queue AS
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
    companies.address AS company_address,
    companies.activity_code,
    candidates.shared_words
FROM int.links AS links
JOIN int.places AS places USING (snapshot_month, cid)
JOIN int.rules AS rules USING (rule)
JOIN int.candidates AS candidates USING (snapshot_month, cid, rule)
JOIN int.companies AS companies
    ON companies.snapshot_month = links.snapshot_month AND companies.ja_kodas = candidates.ja_kodas
WHERE links.tier = 'review';
