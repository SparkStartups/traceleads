-- The lead list as written to output/<month>/leads.csv. Register and Google text that a
-- spreadsheet would run as a formula is quoted: anyone can name a place on Google.
CREATE OR REPLACE MACRO mart.spreadsheet_text(text) AS
    CASE WHEN regexp_matches(text, '^[-=+@\t\r]') THEN '''' || text ELSE text END;

CREATE OR REPLACE VIEW mart.leads_export AS
SELECT * REPLACE (
    mart.spreadsheet_text(company) AS company,
    mart.spreadsheet_text(company_address) AS company_address,
    mart.spreadsheet_text(places) AS places
)
FROM mart.leads;
