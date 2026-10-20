# Leads

A prioritised list of Vilnius businesses that look busy on Google Maps but declare little staff
and tax, for an analyst at VMI (the State Tax Inspectorate) who has to decide where to look
first. The system compares what a business shows the public (how many people review it) with
what its company declares to the state (insured staff at Sodra, taxes paid to VMI), against
similar businesses. Every lead carries the listing and the official records it rests on, the
numbers behind its score, and the innocent explanations to rule out first. These are leads for a
closer look, not accusations.

**Status: transform.** The system is built in stages: infrastructure, collect, load, transform,
publish, the app. The infrastructure, collection, staging tables, and the links from Google
places to companies are built, and October 2026 is collected.
Each section below is updated when its part is built; the results of a real run are added at the
end.

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
name. The register already hides them. From VMI the snapshot keeps only the last quoted part of a
payer's name, the trade name, and drops it when it holds an owner's name: an initial and a name
("V. Petraičio įmonė"), or a first name and a surname in the genitive ("Onos Petraitienės
kavinė"). In October 2026, of 8,270 IĮ payers, 5,422 have no quoted part and keep no name, 137
lose theirs as an owner's name and 2,711 keep a trade name. An IĮ without one is never linked to a
place automatically: only the building rule, which sends a place to review, can find it. The
published list leaves out an IĮ's registered address.

## Collecting a month

`leads collect` downloads each source into `data/raw/<source>/<month>/` and writes the month's
snapshot to `data/snapshots/<month>/`: one Parquet file per source with only the fields the system
uses, and a manifest per source with each raw file's URL, SHA-256 and download time.

- Only the current month can be downloaded, because the sources publish their current state. An
  earlier month is rebuilt from the raw files saved for it (`leads collect --month YYYY-MM`), and
  a rerun downloads only what is missing.
- A download that is not the file asked for, such as a web page, is refused; so is such a file
  saved into the raw folder by hand, and the error names the file to replace.
- Sodra publishes a month about four weeks after it ends, so its latest month is two months
  before the snapshot month, or three if a release is late. Only the files of the years that
  can hold its latest three months, five to two months back, are downloaded. Columns are
  matched by the code in brackets that ends each header cell, since the header text changes
  between years.
- Google Maps is searched for each category keyword in each of Vilnius' 21 elderships, since a
  results list shows about 20 places: 84 pages, rendered by the Oxylabs Web API, which needs
  `OXYLABS_API_KEY` in `.env` (copy `.env.example`). About one render in four comes back
  without the page's JavaScript run, so a page is tried up to five times, and one run renders
  at most 200 times. A card the parser does not recognise stops the snapshot rather than
  saving a guess.
- The snapshot replaces the month's folder only when every source succeeded.
- A raw file's modification time is recorded as its download time, so raw files are copied with
  their times (`cp -p`); otherwise a rebuilt snapshot differs from the committed one.

| Source | Downloaded | Kept in the snapshot |
|---|---|---|
| Register of Legal Entities (`jar`) | the bulk CSV of registered entities | code, name, address, registration date, legal form, status, file date |
| Sodra (`sodra`) | the zipped monthly CSV of each year that holds Sodra's latest three months | company code, month, insured people, activity code |
| VMI taxes paid (`vmi_taxes`) | this year to date and the two years before, from the data.gov.lt API, page by page | company code, trade name, year, months covered, amount, update date |
| Google Maps (`google_maps`) | one rendered results page per category keyword and eldership | place id, name, Google category, address, coordinates, review count, closed flag, and the query and page it came from |

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

A data-quality check is one query in `sql/dq/<layer>_<name>.sql` that returns the rows breaking a
rule. It runs after its layer's models, and its count and first five rows are recorded in
`meta.dq_results`. It is an `error`, which stops the build, unless its first line is
`-- severity: warn`; a warning is only recorded.

| Layer | Holds |
|---|---|
| `ref` | the configuration: categories, legal forms, the city's bounds, thresholds |
| `stg` | one typed table per source, one row per source record |
| `int` | companies and Google places with comparable name and address keys, and the company each place is linked to |
| `mart` | per-company facts and scores, the lead list, and report views |
| `meta` | build runs and data-quality results |

### Loading: the `stg` tables

Each staging table holds one source's rows for the month, typed, with every column selected by
name, so a renamed source column fails the build.

| Table | One row per |
|---|---|
| `stg.source_files` | raw file behind the month's snapshot: URL, SHA-256, download time, the data's latest period |
| `stg.jar_entities` | registered entity: code, name, registered address, registration date, legal form, status |
| `stg.sodra_monthly` | company and month: insured people and the six-digit activity code; insurers without a Lithuanian company code are left out |
| `stg.vmi_taxes` | company and year: trade name, months covered, amount; when a refresh leaves an earlier month's row, only the latest counts |
| `stg.google_listings` | place and query: name, Google category, address, coordinates, review count, closed flag |

Their checks stop the build when a source has no rows, a key repeats, a company code does not have
nine digits, Sodra's latest month is more than three months old, or the register shows a name for
an IĮ, which it hides because the name may be the owner's. A results list that is empty or full
(20 places, so more may have been left out) is reported as a warning.

### Transforming: companies and places

The configuration in `config.py` is written into `ref` tables each time the warehouse opens. These
models read the Google categories of each category, the legal forms that run businesses, the
city's name and bounds, and the generic words, those of the city's name and of the categories'
keywords and Google categories.

| Table | One row per |
|---|---|
| `int.companies` | active company of a business form (UAB, MB, IĮ, VšĮ, AB): name, legal form, registration date, brand and core, and street and house number for an address in Vilnius; an IĮ goes by its VMI trade name, or by none |
| `int.places` | Google place, merged across the queries that found it: the most reviews any query saw, closed if any saw it closed, brand, core, street and house number, and scope |

A place is `in_scope` inside the city's bounds with a Google category of the category that found
it, else `outside_city` (a search by eldership also finds Kaunas' Verkiai) or `other_activity` (a
café search also finds restaurants, and places that show no Google category). In October, 516 of 745 places are in scope: 162 cafés and
bakeries, 191 car repair shops and 163 dental clinics. The checks stop the build when a key
repeats or no place is in scope, and report places in scope without a street or house number.

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

A place's candidates (`int.candidates`) are the companies that share its brand, its building, or
a rare word on its street, each with the evidence the pair shares. A rare word has three letters
or more, is not a number, is used by 30 company names at most, and is not part of the street's
name, so "Antakalnio servisas" and a company on Antakalnio gatvė share nothing. A company's
activity fits when its latest activity class in Sodra is one of the category's: 56.11, 10.71,
10.72 or 47.24 for cafés and bakeries, 95.31 for car repair, 86.23 for dental clinics. In October,
439 of the 516 places in scope have candidates, 8,916 in all.

Each candidate carries the first rule it meets, if any, and `int.links` holds one row per place in
scope: its company, tier and deciding rule, or `unmatched` when no candidate meets a rule.
`mart.review_queue` lists the deciding rule's candidates of every place in review, with both
addresses; an IĮ without a trade name shows only its code and address. A link by brand and activity
whose brand another company also uses is reported, since the brand alone may not tell which of them
runs the place.

| October, places in scope | Automatic | Review | Unmatched |
|---|---|---|---|
| Cafés and bakeries | 36 | 20 | 106 |
| Car repair | 65 | 15 | 111 |
| Dental clinics | 76 | 32 | 55 |
| All | 177 | 67 | 272 |

Of the automatic links, 69 are by brand and building, 95 by brand and activity and 13 by core name
and building.

Labels in `data/labels/match_labels.csv` say whether a company really runs a place: one row per
link, with `selection` (`random` for a link drawn to measure its rule, `flagged` for a flagged
company's link checked by hand) and `correct` (`yes` or `no`); rows without a verdict are left out.
A link labelled wrong is `rejected`: it is never scored and leaves the review queue.
`mart.match_precision` gives each rule's precision on its random labels with a 95% Wilson interval;
flagged links stay out of it, since they were not drawn at random. A label whose selection or
verdict cannot be read stops the build, and a label whose link the rules no longer make is reported.
The file has only its header until the October sample is labelled.

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

## Run it

Requires Docker with Compose v2.24 or later.

```bash
docker compose up
```

This builds the image and runs `leads build`, which rebuilds the warehouse from
`data/snapshots/` into `warehouse/leads.duckdb`. With no month in `data/snapshots/` it stops,
reports that there is no snapshot and exits with code 1. Runs in Docker record their commit as
`unknown`: the image holds no git history.

`docker compose run --rm pipeline collect` collects the current month in Docker.

## Develop and test

Requires [uv](https://docs.astral.sh/uv/).

```bash
make test     # run the tests
make lint     # check the lock file, lint and formatting
make format   # apply lint fixes and formatting
make collect  # download the current month's sources and write its snapshot (needs .env)
make build    # rebuild the warehouse from every snapshot month
```

CI runs `make lint test build` on every push, so every push also builds the committed snapshots.

## Layout

```
src/leads/          config, CLI, warehouse build, run log, checks
src/leads/collect/  one module per source
src/leads/app/      the Streamlit app
sql/                stg, int, mart, dq (checks), analyst (saved queries)
data/snapshots/     committed inputs of each month
data/labels/        hand-labelled links
warehouse/          the built DuckDB file (not committed)
output/             committed lead list of each month
tests/              pytest, no network
```

Design decisions and the alternatives rejected are in [DECISIONS.md](DECISIONS.md).
