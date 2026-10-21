-- Flagged companies' places on Google and the evidence that linked each
SELECT
    scores.snapshot_month,
    scores.rank,
    scores.tier,
    companies.name AS company,
    scores.ja_kodas,
    places.name AS place,
    places.address AS place_address,
    places.review_count,
    links.rule,
    candidates.same_brand,
    candidates.same_core,
    candidates.same_building,
    candidates.same_street,
    candidates.shared_words,
    candidates.fitting_activity,
    mart.maps_url(places.cid) AS maps
FROM mart.scores AS scores
JOIN int.companies AS companies USING (snapshot_month, ja_kodas)
JOIN int.links AS links USING (snapshot_month, ja_kodas)
JOIN int.places AS places USING (snapshot_month, cid)
JOIN int.candidates AS candidates USING (snapshot_month, cid, ja_kodas)
WHERE scores.tier IN ('lead', 'watch') AND links.tier = 'automatic'
ORDER BY scores.snapshot_month DESC, scores.rank, places.review_count DESC;
