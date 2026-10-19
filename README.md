# Leads

A prioritised list of Vilnius businesses that look busy on Google Maps but declare little staff
and tax, for an analyst at VMI (the State Tax Inspectorate) who has to decide where to look
first. The system compares what a business shows the public (how many people review it) with
what its company declares to the state (insured staff at Sodra, taxes paid to VMI), against
similar businesses. Every lead carries the listing and the official records it rests on, the
numbers behind its score, and the innocent explanations to rule out first. These are leads for a
closer look, not accusations.

**Status: design.** The system is built in stages: infrastructure, collect, load, transform,
publish, the app. Each section below is updated when its part is built; the results of a real run
are added at the end.

## Scope

- **City:** Vilnius.
- **Categories:** cafés and bakeries, car repair, dental clinics. Each has enough companies in
  Vilnius to compare against, a distinct activity (EVRK) class, a clear Google category, and
  customers who pay on the spot.
- **Period:** one snapshot a month, kept, so months can be compared.

## Sources

| Source | What the system takes |
|---|---|
| Register of Legal Entities (JAR), Registrų centras | every registered company: code, name, registered address, legal form, registration date, status |
| Sodra, atvira.sodra.lt | insured people per employer and month, and the employer's activity class |
| VMI taxes paid, data.gov.lt | taxes paid per company and year |
| Google Maps, rendered through the Oxylabs Web API | per place: id, name, Google category, address, coordinates, review count, closed flag |

Only the fields the system uses are kept.

Individual enterprises (IĮ) are one person's business, and their names are often the owner's
name. The snapshot keeps only the trade name in quotes, and the published list leaves out an IĮ's
registered address.

## How it works

```
collect    sources            ->  data/raw/<source>/<month>/     files as fetched (not committed)
                              ->  data/snapshots/<month>/        Parquet + manifest (committed)
load       snapshots          ->  stg     one typed table per source
transform  stg                ->  int     companies, places, links between them
           int                ->  mart    company facts, scores, reports
publish    mart               ->  output/<month>/leads.csv       the lead list (committed)
app        Streamlit on the published warehouse, read-only
```

`collect` is the only step that uses the network. `build` runs everything after it offline: it
rebuilds every snapshot month into a new DuckDB file, runs data-quality checks after each layer,
and publishes the file only if no blocking check fails. The warehouse is a function of the
snapshots, the labels and the code, so it never needs a migration and a test can rebuild the
committed month byte for byte.

| Layer | Holds |
|---|---|
| `ref` | the configuration: categories, legal forms, the city's bounds, thresholds |
| `stg` | one typed table per source, one row per source record |
| `int` | companies and Google places with comparable name and address keys, and the company each place is linked to |
| `mart` | per-company facts and scores, the lead list, and report views |
| `meta` | build runs and data-quality results |

## Linking a place to a company

A Google listing has no company code, so the link is inferred from names and addresses. Names are
reduced to a brand (the legal name's quoted part, without the legal form) and a core (the brand
without generic words such as "kavinė"); addresses to a street and a house number. Five rules are
tried in order, and the first that finds a company decides:

| Rule | Evidence | Tier |
|---|---|---|
| 1 | same brand, registered in the same building | automatic |
| 2 | same brand, an activity class that fits the category | automatic |
| 3 | same core name, same building | automatic |
| 4 | a rare word in both names, same street | review |
| 5 | the only company in the building whose activity fits | review |

Only automatic links are scored. Two candidates under the deciding rule send the place to review
without a company. A sample of links per rule is labelled by hand to measure each rule's
precision.

## Busy, and quiet on paper

- **Unit:** the company, with the reviews of all its automatically linked places summed.
- **Busy:** at least the category's median reviews, and at least 50.
- **Declared:** staff is the average insured over Sodra's latest three months, plus one owner for
  an MB or IĮ; tax is VMI's amount for the last full year.
- **Peers:** companies of the same category and legal-form group that run one place, the company
  itself left out; within its review tercile when that leaves enough of them.
- **Gap:** staff or tax at most a third of the peers' median.
- **Status:** busy with both gaps is a `lead`; busy with one gap is `watch`, unless the other
  figure is above the peers' median. Leads come first, ordered by the euro gap to the peers'
  tax.
- **Held, not judged,** with the reason shown: every place closed, registered after January of
  the tax year, no VMI record (a missing row is not zero), too few peers.

## Trusting the list

- **Data-quality checks** after every layer; a failing blocking check stops the build and
  nothing is published.
- **Link precision** per rule from the hand-labelled sample, with a 95% interval.
- **Sensitivity:** the lead list under other gap ratios and busy cutoffs.
- **Coverage:** from places found to companies judged, per category.
- **Reproducibility:** a rebuild of the committed snapshot gives the committed lead list.

## The analyst's app

- **Leads:** the month's list. A chosen company shows its places with Google Maps links, its
  register record, its Sodra months, its VMI row and the raw files they came from.
- **Overview:** the share flagged per category, sensitivity, coverage.
- **Month over month:** what changed since the previous snapshot.
- **Matching:** precision per rule and the review queue.
- **Runs and checks:** each build and its check results.
- **SQL console:** the analyst's own questions on a read-only connection, with saved queries.

## Layout

```
src/leads/          config, CLI, warehouse build, run log, checks
src/leads/collect/  one module per source
src/leads/app/      the Streamlit app
sql/                stg, int, mart, dq (checks), analyst (saved queries)
data/snapshots/     committed inputs of each month
data/labels/        hand-labelled links
output/             committed lead list of each month
tests/              pytest, no network
```

Design decisions and the alternatives rejected are in [DECISIONS.md](DECISIONS.md).
