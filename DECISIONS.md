# Decisions

> One trade-off runs through every choice here: **precision over recall**. Flagging an honest
> business costs the analyst an inspection and the business its good name; missing a lead only
> costs coverage.

## Nine calls, and what lost

| | Question | The call | Rejected |
|---|---|---|---|
| **1** | Where do "busy" and "declared" come from? | Google Maps search pages, rendered by the Oxylabs Web API and parsed in Python; the Register of Legal Entities (name, address, legal form, age), Sodra (insured people per month, activity class) and VMI taxes paid per year, all downloaded by the collector. | The Google Places API, whose terms restrict storing results, which monthly snapshots need; financial statements, a year late; downloading Sodra by hand, which a monthly job cannot do. |
| **2** | Which businesses? | Cafés and bakeries, car repair, dental clinics: enough Vilnius companies for peer groups, a distinct activity class, a clear Google category, customers who pay on the spot. | Hair and beauty, where self-employed people renting chairs outnumber companies; bars and vets, with too few peers. |
| **3** | How is a month kept? | `collect` (online) freezes each source into a Parquet snapshot with a manifest of its raw files; `build` (offline) rebuilds every month into one DuckDB file through SQL models `stg → int → mart`, checks after each layer, and publishes only if no blocking check fails. No migrations, every month scored by the same code, the list reproduced byte for byte; about 12.5 MB a month. | PostgreSQL and dbt, a server and a framework for one analyst's twenty-odd models; appending each month to the published file, which a changed table breaks. |
| **4** | Where do categories and thresholds live? | Once, in `config.py`, written into `ref` tables that the SQL reads. | Constants in both the collector and the SQL, which drift apart. |
| **5** | Which company runs a listing? | A listing has no company code, so an ordered cascade of five rules decides. Three link automatically: the same brand in the same building; the same brand with a fitting activity class; the same name without generic words in the same building. Two only queue the place for a person: a rare shared word on the same street; the only fitting company in the building. An address alone never links automatically, since most Vilnius companies share buildings. A link labelled wrong is never scored. | Name similarity such as Jaro-Winkler, which rates "Antakalnio servisas" and "Antakalnio juvelyrika" as close, since district names start many business names; a weighted score, with too few labels to fit it. |
| **6** | What is busy, and what is quiet? | Busy: lifetime reviews at or above the category's median and at least 50. Quiet, twice: staff (average insured over Sodra's latest three months) and the last full year's tax, each at most a third of the peers' median. Peers: single-place companies of the same category and legal-form group, not closed, young or without a tax record, within the review tercile when it holds enough. Both gaps make a `lead`; one puts a company on `watch`, unless its other figure is above the median. Ordered by the euro gap to the peers' tax, never called evaded tax. | A reviews-per-employee norm, blind to how categories differ; a trained model, with no confirmed cases to fit it; average wage, which Sodra hides for employers with one to three insured. |
| **7** | What if a figure is missing? | Hold the company, with the reason shown: every place closed, registered after January of the tax year (a partial year of tax), too few peers, or no VMI row. A missing Sodra row is zero, since Sodra lists every employer. Every company shows the innocent explanations its data allows. | Reading a missing VMI row as zero tax, which would flag the real payers VMI leaves out. |
| **8** | What about owners' names? | An IĮ, one person's business, keeps only the trade name in quotes, dropped too when it holds the owner's name; its registered address, often a home, stays out of the list. | Keeping full names in the snapshot and hiding them in the app, which would still commit them. |
| **9** | How does the analyst ask questions? | A local Streamlit app over the read-only warehouse: leads with their evidence, overview, month over month, matching, runs and checks, and a read-only SQL console, so no question needs a rerun. | A BI server or a hosted dashboard, more moving parts for one analyst. |

## What was cut

Other Google signals (ratings, opening hours, reviews over time); more evidence per link
(company-first searches, food-safety and cash-register premises, company codes on websites);
scheduling and alerting, since the analyst runs `collect` and `build`. The README's roadmap lists
what comes next.

## Known limitations

Where the list can be wrong is measured in the README; these are limits of the data:

- **One month, once.** Only the current month can be collected, since the sources publish their
  current state: a month missed is a gap for good. Month-over-month starts after October.
- **Sodra in early March.** A new year's file is asked for as soon as its January can be
  published, so an early-March `collect` fails until Sodra publishes January and it is rerun.
- **Tax lags reviews.** Tax is the last full year's: October 2026 sets 2025's taxes against today's
  reviews.
- **Sole traders are invisible.** They are not companies in these registers.
- **Nameless IĮ.** Two thirds of IĮ payers keep no trade name (5,559 of 8,270 in October), so only
  the building rule, which sends a place to review, can find them; the owner-name rule also drops
  the odd abbreviation with dots.
- **Timestamps matter.** A raw file's modification time is its download time, so a copy of
  `data/raw/` without timestamps rebuilds a snapshot that differs from the committed one.
