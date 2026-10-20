-- Per month and category: the places Google showed and how far they got, out of scope or in it
-- and then linked, and the linked companies by tier. The flagged share, leads and watch among the
-- judged companies, tells which category has the most companies busy in public, quiet on paper.
CREATE OR REPLACE VIEW mart.category_summary AS
WITH places AS (
    SELECT
        places.snapshot_month,
        places.category,
        count(*) AS places,
        count(*) FILTER (places.scope = 'outside_city') AS outside_city,
        count(*) FILTER (places.scope = 'other_activity') AS other_activity,
        count(*) FILTER (places.scope = 'in_scope') AS in_scope,
        count(*) FILTER (links.tier = 'automatic') AS linked,
        count(*) FILTER (links.tier = 'review') AS in_review,
        count(*) FILTER (links.tier = 'rejected') AS rejected,
        count(*) FILTER (links.tier = 'unmatched') AS unmatched
    FROM int.places AS places
    LEFT JOIN int.links AS links USING (snapshot_month, cid)
    GROUP BY places.snapshot_month, places.category
),
companies AS (
    SELECT
        facts.snapshot_month,
        facts.category,
        count(*) AS companies,
        count(*) FILTER (scores.tier = 'held') AS held,
        count(*) FILTER (scores.tier <> 'held') AS judged,
        count(*) FILTER (scores.busy AND scores.tier <> 'held') AS busy,
        count(*) FILTER (scores.tier = 'lead') AS leads,
        count(*) FILTER (scores.tier = 'watch') AS watch
    FROM mart.company_facts AS facts
    JOIN mart.scores AS scores USING (snapshot_month, ja_kodas)
    GROUP BY facts.snapshot_month, facts.category
)
SELECT
    snapshot_month,
    category,
    coalesce(places.places, 0) AS places,
    coalesce(places.outside_city, 0) AS outside_city,
    coalesce(places.other_activity, 0) AS other_activity,
    coalesce(places.in_scope, 0) AS in_scope,
    coalesce(places.linked, 0) AS linked,
    coalesce(places.in_review, 0) AS in_review,
    coalesce(places.rejected, 0) AS rejected,
    coalesce(places.unmatched, 0) AS unmatched,
    coalesce(companies.companies, 0) AS companies,
    coalesce(companies.held, 0) AS held,
    coalesce(companies.judged, 0) AS judged,
    coalesce(companies.busy, 0) AS busy,
    coalesce(companies.leads, 0) AS leads,
    coalesce(companies.watch, 0) AS watch,
    (companies.leads + companies.watch) / nullif(companies.judged, 0) AS flagged_share
FROM places
FULL JOIN companies USING (snapshot_month, category);
