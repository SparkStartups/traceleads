# Leads

A prioritised list of Vilnius businesses that look busy on Google Maps but declare little staff
and tax, for an analyst at VMI (the State Tax Inspectorate) who has to decide where to look
first. The system compares what a business shows the public (how many people review it) with
what its company declares to the state (insured staff at Sodra, taxes paid to VMI), against
similar businesses. Every lead carries the listing and the official records it rests on, the
numbers behind its score, and the innocent explanations to rule out first. These are leads for a
closer look, not accusations.

## October 2026

The committed run is October 2026, and its list is `output/2026-10/leads.csv`.

- 84 Google Maps searches found 745 places; 516 are in Vilnius under a Google category of the
  category that searched for them.
- 177 places link automatically to 157 companies; 64 wait in the review queue, 3 links were
  labelled wrong, and 272 places found no company.
- Of the 157 companies, 8 are held without a judgement and 149 are judged: 2 leads, both car
  repair shops, and 8 on watch.
- Cafés and bakeries have the highest flagged share, 11% (2 of 19 judged), then car repair, 9% (5
  of 57), and dental clinics, 4% (3 of 73).

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

Registrų centras, Sodra and VMI (through data.gov.lt) publish these files as open data. Collecting
stays light: one pass a month, every request the collector makes with the project's own User-Agent,
and every file saved in `data/raw/` so that a rerun downloads only what is missing and a build reads
only the saved snapshot. Google Maps pages are rendered by the Oxylabs Web API, a paid service, and
from each place only the fields above are kept, with no review text and nothing about reviewers.

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
café search also finds restaurants, and places that show no Google category). In October, 516
of 745 places are in scope: 162 cafés and bakeries, 191 car repair shops and 163 dental clinics.
The checks stop the build when a key repeats or no place is in scope, and report places in scope
without a street or house number.

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
addresses, except an IĮ's registered address, and the number of companies registered in the
candidate's building (in October, rule 5 decides in buildings of 1 to 80, median 8); an IĮ
without a trade name shows only its code. A link by brand and activity whose brand another
company also uses is reported, since the brand alone may not tell which of them runs the place.

| October, places in scope | Automatic | Review | Rejected | Unmatched |
|---|---|---|---|---|
| Cafés and bakeries | 36 | 18 | 2 | 106 |
| Car repair | 65 | 15 | 0 | 111 |
| Dental clinics | 76 | 31 | 1 | 55 |
| All | 177 | 64 | 3 | 272 |

Of the automatic links, 69 are by brand and building, 95 by brand and activity and 13 by core name
and building.

Labels in `data/labels/match_labels.csv` say whether a company really runs a place: one row per
link, with `selection` (`random` for a link drawn to measure its rule, `flagged` for a flagged
company's link checked by hand) and `correct` (`yes` or `no`); rows without a verdict are left out.
A link labelled wrong is `rejected`: it is never scored and leaves the review queue.
`mart.match_precision` gives each rule's precision on its random labels with a 95% Wilson interval;
flagged links stay out of it, since they were not drawn at random. A label whose selection or
verdict cannot be read stops the build, and a label whose link the rules no longer make is reported.
The October sample is 10 links per rule drawn at random and the 10 flagged companies' links. Its
verdicts are proposed from names, addresses and activity codes and still to be checked by hand:
50 yes, 3 no, and 7 left blank where names and addresses cannot tell.

| Rule | Tier | Labelled | Right | Precision (95% interval) |
|---|---|---|---|---|
| 1 brand and building | automatic | 10 | 10 | 1.00 (0.72–1.00) |
| 2 brand and activity | automatic | 10 | 10 | 1.00 (0.72–1.00) |
| 3 core name and building | automatic | 10 | 10 | 1.00 (0.72–1.00) |
| 4 rare word on the street | review | 10 | 7 | 0.70 (0.40–0.89) |
| 5 only fitting company in the building | review | 3 | 3 | 1.00 (0.44–1.00) |

The 7 blank verdicts are all rule 5's: its places' names are too generic to tell, so its 3 of 3
are the easy cases and do not yet measure the rule.

The three wrong links share only a generic word with the place; they are rejected, so the review
queue holds 69 rows instead of 72. Every flagged company's link is right, so the list is unchanged.

## Busy, and quiet on paper

`mart.company_facts` holds, for every company with an automatic link, what the score compares:
its category (that of its busiest place), places, reviews, whether every place is closed, whether
it is an MB or IĮ, its registration date, and its insured staff and tax as defined below. A month
without a Sodra row had nobody insured; a company without a VMI row covering the whole tax year
has no known tax. In October that is 157 companies, 153 of them with a tax row.

- **Unit:** the company, with the reviews of all its automatically linked places summed.
- **Busy:** at least the category's median reviews, and at least 50.
- **Declared:** staff is the average insured over Sodra's latest three months, plus one owner for
  an MB or IĮ; tax is VMI's amount for the last full year.
- **Peers:** companies of the same category and legal-form group that run one place and are not
  closed, young or without a tax record, the company itself left out; within its review tercile
  when that leaves enough of them.
- **Gap:** staff or tax at most a third of the peers' median.
- **Status:** busy with both gaps is a `lead`; busy with one gap is `watch`, unless the other
  figure is above the peers' median. Leads come first, ordered by the euro gap to the peers'
  tax.
- **Held, not judged,** with the reason shown: every place closed, registered after January of
  the tax year, no VMI record (a missing row is not zero), too few peers.
- **Innocent explanations,** shown with every company, to rule out first: owner-operated (the
  staff counts one owner; more may work off the payroll), registered in the tax year or the
  year before (it was among its first years), several places (peers run one), the category's own
  (dentists often bill through their own companies), nobody insured with under 1000 € of tax (it
  may no longer run the place).

`mart.scores` holds each company's tier (`lead`, `watch`, `not_flagged` or `held`), its hold reason,
and, unless it was held before its peers were counted, its peer group, number of peers, whether it
is busy, its staff and tax against the peers' medians, and the euro gap to the peers' tax. Flagged
companies are ranked: leads first, then watch, each by that euro gap. The limits are in
`ref.scoring`: at least 5 peers, the review tercile when it alone leaves at least 8, at least 50
reviews, and a gap at a third of the peers' median.

| October | Companies |
|---|---|
| Lead | 2 (car repair) |
| Watch | 8 (3 car repair, 3 dental, 2 cafés and bakeries) |
| Not flagged | 139 |
| Held | 8: 3 without a tax record, 2 registered after January 2025, 3 owner-operated cafés with 2 peers each |

Car repair shops and dental clinics that are not owner-operated are compared within their review
tercile; the others across their category. Of the flagged companies, only the three dental clinics
carry an explanation; none is owner-operated, young or runs several places.

`mart.category_summary` follows each category from the places Google showed to the companies
judged; its flagged share is leads and watch among the judged companies. `mart.sensitivity`
tiers the judged companies again under each gap ratio (a half, a third, a quarter) and minimum of
reviews (25, 50, 100) in `ref.sensitivity`, with peers and holds as scored, and counts how many
of the month's leads stay leads.

| October | Places | In scope | Linked | Companies | Judged | Leads | Watch | Flagged share |
|---|---|---|---|---|---|---|---|---|
| Cafés and bakeries | 361 | 162 | 36 | 22 | 19 | 0 | 2 | 11% |
| Car repair | 202 | 191 | 65 | 61 | 57 | 2 | 3 | 9% |
| Dental clinics | 182 | 163 | 76 | 74 | 73 | 0 | 3 | 4% |

Both October leads stay leads at a gap of a half or a third with any minimum of reviews; at a half
there are 5 to 8 leads, and at a quarter none of them is one.

`mart.month_over_month` sets each month's scored companies against the month built before it:
`new`, `gone`, `tier changed` or `unchanged`, with what moved each one: linked or no longer linked
to a place, held or judged again, a new category, busy or no longer (with the reviews and the
category's median), and on a new tier the staff and tax that changed, with the peers' medians of
both months. Every build scores all months with the same code, so a change comes from the data.
October is the first month, so it has nothing to compare with.

## Reading a lead

`leads build` writes each month's list to `output/<month>/leads.csv` from the published
warehouse's `mart.leads`: leads, then watch, in rank order, one row per company.

| Columns | What they say |
|---|---|
| `rank`, `status`, `ja_kodas`, `company`, `company_address`, `category` | which company, and how flagged |
| `reviews`, `category_median_reviews`, `places` | how busy, and on which Google places, each with its Maps link |
| `staff`, `peer_median_staff`, `staff_ratio` | declared staff against the peers' median |
| `tax_year`, `tax`, `peer_median_tax`, `tax_ratio`, `tax_gap_eur` | the last full year's tax against the peers' median, and the euro gap |
| `peer_group`, `peers` | whom it was compared with |
| `reason` | the numbers above in one line, each gap named |
| `explanations` | the innocent explanations to rule out first |

A reason reads: "176 reviews, category median 91.0; staff gap: 3.3 against the peers' 11.7
(29%); tax gap: 7565 € in 2025 against the peers' 118049 € (6%)". An IĮ's registered address is
left out of the list and the review queue, since it is often its owner's home. Text from the
register or Google that a spreadsheet would run as a formula (starting with `=`, `+`, `-`, `@`, a
tab or a carriage return) is quoted in the file, since anyone can name a place on Google.

## How the list is checked

The cost of flagging an honest business shapes each step:

- **Only confident links are scored.** The three automatic rules are right in all 30 links
  sampled, and every flagged company's link is labelled right. A place two companies could run,
  or one linked by a single shared word or by its building alone, waits for a person.
- **Both figures, and peers.** A lead needs a staff gap and a tax gap against at least 5 similar
  companies; one gap only puts a company on watch. 8 companies are held, with the reason shown,
  rather than judged on missing data.
- **Data-quality checks** run after every layer: 15 in October's build. The 11 that block a
  build all pass; of the 4 warnings, two report rows: 35 results lists that came back empty (7)
  or full (28, so they may have left places out), and 24 places in scope without a street or
  house number.
- **Sensitivity:** both leads stay leads at a gap of a half or a third with any minimum of
  reviews.
- **Coverage:** each category followed from the places Google showed to the companies judged.
- **Reproducibility:** a test rebuilds the committed snapshot and compares the lead list byte for
  byte; the tests need no network, and CI runs them, the lint and the build on every push.

## Limitations

Where the list can be wrong, measured on October.

**Wrong matches**

- **A brand anywhere.** Rule 2 links by brand and activity wherever the company is registered, so 28
  of the 177 automatic links reach companies registered outside the city, 9 of them in Šiauliai, and
  3 more reach companies at a 'Vilniaus m. sav.' address without a Vilnius street: a chain run from
  elsewhere, or a namesake. One company on watch is registered outside the city.
- **One company, many places.** A café chain links to 9 places, whose reviews are summed; 7
  companies link to more than one place, and none of them is flagged.
- **Addresses the keys miss.** Building keys are read only from an address that starts 'Vilnius,'.
  812 active companies are registered at one that starts 'Vilniaus m. sav.': 478 with nothing more,
  334 in Grigiškės and nearby villages, with a street and number the keys do not read. Only rule 2
  can link them: in October it links 3, one to a place in its own building in Grigiškės, which rule
  1 would have found.
- **Streets that end alike.** A street counts as the same when its key ends with the other's, for a
  first name the register spells out ('loretos asanaviciutes' and 'asanaviciutes'); it also takes
  'seskines sodu' for 'sodu'. 32 register street pairs end alike, 22 of them in 'sodu'. In October
  18 such pairs join a place and a company: 3 automatic links and 2 candidates in review rest on a
  spelled-out first name, as meant, and the one 'sodu' pair links nothing.
- **Individual enterprises.** 3 of the 177 automatic links reach an IĮ. Most IĮ keep no name after
  masking, so they can only reach the review queue, through their building.
- **Small samples.** Each rule's precision rests on at most 10 labelled links: the automatic rules'
  interval starts at 0.72, rule 4 is right in 7 of 10, and rule 5 is not measured yet. The verdicts
  are proposed and still to be checked by an analyst.

**False positives**

- **Lifetime reviews.** Reviews accumulate, so a place busy years ago still looks busy; one month
  cannot show which reviews are recent.
- **Work off the payroll.** Sodra counts insured people only: contractors, family help and owners of
  an MB beyond the one counted look like missing staff.
- **Revenue in another company.** VMI reports tax per company, so a business that bills through a
  related company looks quiet; the dental clinics carry this explanation.
- **Exactly a third.** The gap is compared in floating point: staff of 2 against a median of 6
  counts as a gap (one October company, not busy, so not flagged), but 1.1 against 3.3 does not.
- **Places Google left out.** A full results list may hide places, so a company's reviews can be
  undercounted, and a busy business missed.

## Roadmap

**Scalability: from three categories in Vilnius to every business in Lithuania**

- The declared side already covers the country: the register, Sodra and VMI files hold every
  company, and only the city and the categories narrow them. A category is one entry in `config.py`.
- Google is the limit: a keyword per eldership gives 84 pages for three categories in one city.
  Nationally, search map tiles per category, split a tile whose list is full, and render
  concurrently through Oxylabs' asynchronous API.
- Snapshots move from git (about 12.5 MB a month) to object storage, partitioned by month and
  source; DuckDB reads Parquet there in place, and a build adds the new month instead of rebuilding
  all of them once that gets slow.

**Accuracy of matching and scoring**

- More evidence per link: VMI cash-register and food-safety premises addresses, company codes on
  business websites, and geocoded register addresses instead of street keys.
- Larger labelled samples per rule, with precision tracked each month, and a person's verdict in the
  review queue linking the place.
- Busy measured by reviews gained between monthly snapshots, not lifetime totals.
- Gap and busy limits calibrated on inspection outcomes once VMI returns them; until then the
  sensitivity grid shows what each choice changes.

**Data freshness and updates**

- Each source on its own clock: the register changes daily, Sodra publishes monthly about four weeks
  late, VMI refreshes this year's row monthly and closes a year in January, and listings change any
  day. Collect each when its file changes (its date or SHA-256), not all at once.
- A stale source already stops the build (Sodra more than three months old); the other sources get
  the same check.
- Re-render flagged and queued places more often than the rest.

**Monitoring, observability and data quality**

- Already: every run with its commit and duration in `meta.pipeline_runs`, every check's count and
  first rows in `meta.dq_results`, both shown in the app.
- Next: an alert when a build fails or a warning's count jumps, month-over-month checks of rows per
  source and category, and each run's render failures and cost.

**Cost**

- The registers are free downloads; Google rendering is the only paid part: 84 pages a month, each
  rendered up to five times, since about one render in four comes back without the page's JavaScript
  run.
- At scale: re-render only lists that were full or changed, search by tile so no page is spent on
  another city, and, if its terms come to allow kept monthly snapshots, weigh a Google Places API
  licence against rendering.

## The analyst's app

- **Leads:** the month's list. A chosen company shows its reason, its innocent explanations,
  its places with Google Maps links and the queries that found them, its register record (an
  IĮ's address withheld), its insured people in the months scored, its VMI rows and the raw files
  they came from, with their SHA-256.
- **Overview:** per category, the places Google showed through scope and links to the companies
  judged, with the flagged share; the sensitivity grid, the scoring's own limits marked.
- **Month over month:** the changes since the month built before, counted and listed with their
  causes; unchanged companies on request.
- **Matching:** each rule's places, links and precision with its interval; the review queue,
  each candidate with the companies registered in its building; a chosen place's candidates with
  the evidence each shares, those meeting no rule on request.
- **Runs and checks:** the published build's run of each month; the month's checks, with the
  first rows behind a failing one; and each source's raw files, rows, period and download.
- **SQL console:** the analyst's own DuckDB SQL on a read-only connection, or a saved query from
  `sql/analyst/` (each file's first line, a comment, is its title). Each query runs in a process
  of its own and stops after a minute, so neither a crash in DuckDB nor a query that never ends
  takes the app down. It reads the tables as built, with an IĮ's registered address.

The app reads the published warehouse only: each query opens its own read-only connection, with
no access to other files, two threads and 1 GB of memory. The pages' queries are cached until a
rebuild replaces the file, which it can do while the app runs. It sends Streamlit no usage
statistics (`.streamlit/config.toml`).

## Run it

Requires Docker with Compose v2.24 or later.

```bash
docker compose up
```

This builds the image and runs `leads build`, which rebuilds the warehouse from
`data/snapshots/` into `warehouse/leads.duckdb` and writes each month's lead list to
`output/<month>/leads.csv`. With no month in `data/snapshots/` it stops,
reports that there is no snapshot and exits with code 1. Runs in Docker record their commit as
`unknown`: the image holds no git history. When the build succeeds, the app serves the
published warehouse at http://localhost:8501.

`docker compose run --rm pipeline collect` collects the current month in Docker.

## Develop and test

Requires [uv](https://docs.astral.sh/uv/).

```bash
make test     # run the tests
make lint     # check the lock file, lint and formatting
make format   # apply lint fixes and formatting
make collect  # download the current month's sources and write its snapshot (needs .env)
make build    # rebuild the warehouse from every snapshot month
make app      # serve the app on the published warehouse at http://localhost:8501
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
