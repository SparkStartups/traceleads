# Leads

A prioritised list of Vilnius businesses that look busy on Google Maps but declare little staff
and tax, for an analyst at VMI (the State Tax Inspectorate) who has to decide where to look
first. The system compares what a business shows the public (how many people review it) with
what its company declares to the state (insured staff at Sodra, taxes paid to VMI), against
similar businesses. Every lead carries the listing and the official records it rests on, the
numbers behind its score, and the innocent explanations to rule out first. These are leads for a
closer look, not accusations.

**Status: collect.** The system is built in stages: infrastructure, collect, load, transform,
publish, the app. The infrastructure and collection are built, and October 2026 is collected.
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

CI runs `make lint test` on every push.

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
