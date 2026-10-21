-- The lead list: leads, then watch, in rank order, each with the numbers behind its tier, the
-- Google places it rests on, a one-line reason and the innocent explanations to rule out first.
-- An IĮ's registered address is withheld: it is often its owner's home.
CREATE OR REPLACE MACRO mart.maps_url(cid) AS 'https://www.google.com/maps?cid=' || cid;

CREATE OR REPLACE VIEW mart.leads AS
WITH places AS (
    SELECT
        links.snapshot_month,
        links.ja_kodas,
        string_agg(
            concat_ws(', ', places.name, places.address)
                || ' ' || mart.maps_url(places.cid),
            '; ' ORDER BY places.review_count DESC, places.cid
        ) AS places
    FROM int.links AS links
    JOIN int.places AS places USING (snapshot_month, cid)
    WHERE links.tier = 'automatic'
    GROUP BY links.snapshot_month, links.ja_kodas
)
SELECT
    scores.snapshot_month,
    scores.rank,
    scores.tier AS status,
    scores.ja_kodas,
    companies.name AS company,
    CASE WHEN NOT forms.named_after_owner THEN companies.address END AS company_address,
    facts.category,
    facts.reviews,
    scores.category_median_reviews,
    places.places,
    round(scores.staff, 1) AS staff,
    round(scores.peer_median_staff, 1) AS peer_median_staff,
    round(scores.staff_ratio, 2) AS staff_ratio,
    facts.tax_year,
    facts.tax,
    round(scores.peer_median_tax, 2) AS peer_median_tax,
    round(scores.tax_ratio, 2) AS tax_ratio,
    round(scores.tax_gap_eur, 2) AS tax_gap_eur,
    scores.peer_group,
    scores.peers,
    concat_ws(  -- a share of a peers' median of 0 is none, and left out
        '; ',
        format('{} reviews, category median {}', facts.reviews, scores.category_median_reviews),
        format(
            '{} {:.1f} against the peers'' {:.1f}',
            CASE WHEN scores.staff_gap THEN 'staff gap:' ELSE 'staff' END,
            scores.staff,
            scores.peer_median_staff
        ) || coalesce(format(' ({:.0f}%)', 100 * scores.staff_ratio), ''),
        format(
            '{} {:.0f} € in {} against the peers'' {:.0f} €',
            CASE WHEN scores.tax_gap THEN 'tax gap:' ELSE 'tax' END,
            facts.tax,
            facts.tax_year,
            scores.peer_median_tax
        ) || coalesce(format(' ({:.0f}%)', 100 * scores.tax_ratio), '')
    ) AS reason,
    array_to_string(scores.explanations, '; ') AS explanations
FROM mart.scores AS scores
JOIN mart.company_facts AS facts USING (snapshot_month, ja_kodas)
JOIN int.companies AS companies USING (snapshot_month, ja_kodas)
JOIN ref.legal_forms AS forms ON forms.code = companies.legal_form
JOIN places USING (snapshot_month, ja_kodas)
WHERE scores.tier IN ('lead', 'watch');
