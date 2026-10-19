# Decisions

The system ranks Vilnius companies that look busy on Google Maps but declare little staff and
tax. One trade-off runs through it: precision over recall. Flagging an honest business costs the
analyst an inspection and the business its good name; missing a lead only costs coverage.

## Key decisions

**1. Google Maps through Oxylabs, and three official registers.** Google Maps search pages are
rendered by the Oxylabs Web API and parsed in Python. The declared side is the Register of Legal
Entities (name, address, legal form, age), Sodra (insured people per month, activity class) and
VMI taxes paid per year. Only the fields the scoring uses are kept.
*Rejected:* the Google Places API, whose terms restrict storing results, which monthly snapshots
need, and whose review counts sit in its most expensive tier; financial statements, which lag a
year; food-safety premises and company codes from websites, which need a crawler of their own.

**2. Three categories: cafés and bakeries, car repair, dental clinics.** Each has enough Vilnius
companies for peer groups, a distinct activity class, a clear Google category, and customers who
pay on the spot. *Rejected:* hair and beauty, where salons rent chairs to self-employed people and
sole traders, invisible to these registers, outnumber companies; bars and vets, with too few
peers; hotels, reviewed mostly elsewhere.

**3. Sodra's yearly files are downloaded by the collector.** Sodra publishes its company data as
one zipped CSV per year. The collector downloads the files that cover the latest months, once a
month, checks that each is the file asked for, and records it in the month's manifest.
*Rejected:* a manual download each month, a step a monthly job cannot run.

**4. One DuckDB file, rebuilt from committed Parquet snapshots.** `collect` (online) freezes each
source into a monthly snapshot with a manifest of each raw file's URL, SHA-256 and download time.
`build` (offline) runs numbered SQL models `stg → int → mart` with data-quality checks after each
layer, and publishes the new warehouse only if no blocking check fails. Every build rebuilds every
month: no migrations, every month scored by the same code, and the committed lead list can be
reproduced byte for byte. *Rejected:* PostgreSQL, a server for one analyst's local tool; dbt, a
framework for about twenty models; appending each month to the published file, where a changed
table breaks the next build.

**5. One configuration in Python, written into `ref` tables.** Categories (keywords, Google
categories, activity classes), legal forms, the city's bounds and every threshold are defined once
in `config.py`; the build writes them into `ref` tables that the SQL reads. No category, code or
threshold is repeated in SQL. *Rejected:* constants spread across the collector and the SQL
files, which drift apart when a category changes.

**6. Matching by an ordered rule cascade; only confident links are scored.** A listing has no
company code, so the first of five rules a place's candidates meet decides. Three rules link
automatically: the same brand in the same building; the same brand with an activity class that
fits the category; the same name without generic words in the same building. Two only send the
place to a review queue: a rare shared word on the same street, and the only fitting company in
the building. An address alone never links automatically, because most Vilnius companies are
registered in buildings shared with many others. A link a person labels wrong is never scored.
*Rejected:* name similarity scores such as Jaro-Winkler, which rate "Antakalnio servisas" and
"Antakalnio juvelyrika" as close because street and district names start many business names; a
weighted match score, with no labels to fit it and no meaning to an analyst.

**7. Busy and quiet, measured against equally busy peers.** Busy is lifetime Google reviews at or
above the category's median and at least 50. Quiet is measured twice, staff (average insured over
Sodra's latest three months) and the last full year's taxes, each against the median of peers:
single-place companies of the same category and legal-form group, within the same review tercile
when it holds enough, the company itself left out. A gap is a third of the peers' median or less.
Both gaps make a `lead`; one puts the company on `watch`, unless its other figure is above the
peers' median. Leads are ordered by the euro gap to the peers' taxes, never called evaded tax.
*Rejected:* a fixed reviews-per-employee norm, which ignores how categories differ; a trained
model, with no confirmed cases to fit or validate it; average wage, which Sodra hides for
employers with one to three insured, most small venues; a fixed number of leads, which would
churn every month.

**8. Holding back rather than guessing.** A company is held, with the reason shown, when its
places are all closed, it was registered after January of the tax year (it paid tax for only part
of it), it has too few peers, or VMI has no row for it: VMI leaves out some real payers, so a
missing row is not read as zero. A missing Sodra row is zero, because Sodra lists every employer.
Each flagged company shows the innocent explanations the data makes plausible: an MB or IĮ owner
off the payroll, a young company, several places, dentists billing through their own companies.

**9. Owners' names stay out.** An individual enterprise (IĮ) is one person's business. The
snapshot keeps only the trade name in quotes from its name, and the published list leaves out its
registered address, often a home.

**10. A local Streamlit app over the read-only warehouse,** with the leads and their evidence,
the category overview, month-over-month changes, matching precision and the review queue, runs
and checks, and a read-only SQL console, so follow-up questions need no rerun.
*Rejected:* a BI server or a hosted dashboard, more moving parts for one analyst.
