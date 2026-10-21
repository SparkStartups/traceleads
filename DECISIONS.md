# Decisions

The system ranks Vilnius companies that look busy on Google Maps but declare little staff and
tax. One trade-off runs through it: precision over recall. Flagging an honest business costs the
analyst an inspection and the business its good name; missing a lead only costs coverage.

## Key decisions

**1. Google Maps through Oxylabs, and three official registers.** Google Maps search pages are
rendered by the Oxylabs Web API and parsed in Python. The declared side is the Register of Legal
Entities (name, address, legal form, age), Sodra (insured people per month, activity class) and VMI
taxes paid per year, all downloaded by the collector. *Rejected:* the Google Places API, whose terms
restrict storing results, which monthly snapshots need; financial statements, which lag a year;
downloading Sodra by hand, which a monthly job cannot do.

**2. Three categories: cafés and bakeries, car repair, dental clinics.** Each has enough Vilnius
companies for peer groups, a distinct activity class, a clear Google category, and customers who
pay on the spot. *Rejected:* hair and beauty, where self-employed people renting chairs outnumber
companies; bars and vets, with too few peers.

**3. One DuckDB file, rebuilt from committed Parquet snapshots.** `collect` (online) freezes each
source into a monthly snapshot with a manifest of its raw files. `build` (offline) runs numbered
SQL models `stg → int → mart` with data-quality checks after each layer, and publishes the new
warehouse only if no blocking check fails. Every build rebuilds every month: no migrations, every
month scored by the same code, and the committed lead list reproduced byte for byte. Each month
adds about 12.5 MB of Parquet to the repository.
*Rejected:* PostgreSQL and dbt, a server and a framework for one analyst's twenty-odd models;
appending each month to the published file, which a changed table breaks.

**4. One configuration in Python, written into `ref` tables.** Categories, legal forms, the
city's bounds and every threshold are defined once in `config.py` and written into `ref` tables
that the SQL reads. *Rejected:* constants in both the collector and the SQL, which drift apart.

**5. Matching by an ordered rule cascade; only confident links are scored.** A listing has no
company code, so the first of five rules a place's candidates meet decides. Three link
automatically (the same brand in the same building or with an activity class that fits the
category; the same name without generic words in the same building); two only send the place to
a review queue (a rare shared word on the same street; the only fitting company in the
building). An address alone never links automatically, because most Vilnius companies are
registered in buildings shared with many others. A link a person labels wrong is never scored.
*Rejected:* name similarity scores such as Jaro-Winkler, which rate "Antakalnio servisas" and
"Antakalnio juvelyrika" as close because street and district names start many business names; a
weighted match score, with too few labels to fit it.

**6. Busy and quiet, measured against equally busy peers.** Busy is lifetime Google reviews at or
above the category's median and at least 50. Quiet is measured twice, staff (average insured over
Sodra's latest three months) and the last full year's taxes, each against the median of peers:
single-place companies of the same category and legal-form group, not closed, young or without a tax
record, within the same review tercile when it holds enough. A gap is a third of the peers' median
or less. Both gaps make a `lead`; one puts the company on `watch`, unless its other figure is above
the peers' median. Leads are ordered by the euro gap to the peers' taxes, never called evaded tax.
*Rejected:* a fixed reviews-per-employee norm, which ignores how categories differ; a trained model,
with no confirmed cases to fit it; average wage, which Sodra hides for employers with one to three
insured.

**7. Holding back rather than guessing.** A company is held, with the reason shown, when its places
are all closed, it was registered after January of the tax year (a partial year of tax), it has too
few peers, or VMI has no row for it: VMI leaves out some real payers, so a missing row is not read
as zero. A missing Sodra row is zero, because Sodra lists every employer. Each company shows the
innocent explanations the data makes plausible, such as an owner off the payroll or dentists billing
through their own companies.

**8. Owners' names stay out.** An individual enterprise (IĮ) is one person's business. The
snapshot keeps only the trade name in quotes from its name, and drops that too when it holds the
owner's name. The published list leaves out its registered address, often a home.

**9. A local Streamlit app over the read-only warehouse,** with the leads and their evidence,
the overview, month-over-month changes, matching, runs and checks, and a read-only SQL console,
so follow-up questions need no rerun.
*Rejected:* a BI server or a hosted dashboard, more moving parts for one analyst.

## What was cut

Other Google signals (ratings, opening hours, reviews over time); more evidence per link
(company-first searches, food-safety and cash-register premises, company codes on websites);
scheduling and alerting, since the analyst runs `collect` and `build`. The README's roadmap lists
what comes next.

## Known limitations

The README measures where the list can be wrong. Limits of the data and its collection:

- Only the current month can be collected, since the sources publish their current state: a month
  missed is a gap for good, and month-over-month changes start after October.
- From March a new year's Sodra file is asked for as soon as its January can be published, so an
  early-March `collect` fails until Sodra publishes January and it is rerun.
- Tax is the last full year's: October 2026 sets 2025's taxes against today's reviews.
- Sole traders are not companies in these registers, so a business one runs is invisible.
- Two thirds of IĮ payers keep no trade name (5,559 of 8,270 in October), so only the building rule,
  which sends a place to review, can find them; the owner-name rule also drops the odd abbreviation
  with dots.
- Every raw file's modification time is its download time, and for a Google page the date its places
  were seen, so a copy of `data/raw/` without timestamps rebuilds a snapshot that differs from the
  committed one.